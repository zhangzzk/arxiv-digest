#!/usr/bin/env python3
"""
arxiv_fetch.py — Fetch arxiv paper metadata (title, authors, abstract, categories)
for given categories and time period.

Primary:   Arxiv Atom API (export.arxiv.org) with submittedDate queries
           + RSS/Atom feeds (rss.arxiv.org) for "today" queries
Fallback:  HTML scraping of arxiv.org/list/{category}/new|recent|pastweek

Usage:
    python3 arxiv_fetch.py --categories astro-ph.CO astro-ph.GA --period today
    python3 arxiv_fetch.py --categories astro-ph.CO --period week
    python3 arxiv_fetch.py --categories astro-ph.CO --period 2025-11-14
    python3 arxiv_fetch.py --categories astro-ph.CO --period 2025-11-10:2025-11-14
    python3 arxiv_fetch.py --prefs /path/to/arxiv_preferences.json --period today

Output: JSON array of paper objects to stdout. Also writes to --output file if specified.

Dependencies: Python 3.8+ standard library only (urllib, xml, html.parser, json, re)
"""

import argparse
import json
import sys
import re
import time
import logging
import socket
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote_plus, urlencode, urlparse, urlunparse
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple

from storage_paths import get_storage_paths

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARXIV_API_BASE = "https://export.arxiv.org/api/query"
ARXIV_RSS_BASE = "https://rss.arxiv.org/atom"
ARXIV_HTML_BASE = "https://arxiv.org/list"
API_DELAY = 3.1  # seconds between API requests (arxiv asks for 3s)
MAX_RESULTS_PER_QUERY = 200  # API max per page
DEFAULT_CHUNK_DAYS = 7  # break long date ranges into smaller API windows
USER_AGENT = "arxiv-digest-skill/1.0 (https://github.com/anthropics/claude)"

# Atom / RSS namespaces
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
def make_paper(
    arxiv_id: str,
    title: str,
    authors: List[str],
    abstract: str,
    categories: List[str],
    primary_category: str = "",
    published: str = "",
    updated: str = "",
    comment: str = "",
    journal_ref: str = "",
    doi: str = "",
    announce_type: str = "new",
) -> Dict:
    """Create a normalized paper dict."""
    return {
        "arxiv_id": arxiv_id.strip(),
        "title": " ".join(title.split()),  # collapse whitespace
        "authors": authors,
        "abstract": " ".join(abstract.split()),
        "categories": categories,
        "primary_category": primary_category or (categories[0] if categories else ""),
        "published": published,
        "updated": updated,
        "comment": comment,
        "journal_ref": journal_ref,
        "doi": doi,
        "announce_type": announce_type,
    }


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _is_dns_error(err: Exception) -> bool:
    """Best-effort detection for DNS resolution failures."""
    if isinstance(err, socket.gaierror):
        return True
    if isinstance(err, URLError):
        reason = getattr(err, "reason", None)
        if isinstance(reason, socket.gaierror):
            return True
        if isinstance(reason, Exception) and _is_dns_error(reason):
            return True
    msg = str(err).lower()
    dns_markers = (
        "name or service not known",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "failed to resolve",
        "getaddrinfo failed",
    )
    return any(marker in msg for marker in dns_markers)


def _fallback_urls(url: str) -> List[str]:
    """
    Return URL candidates to try when a host is unreachable.
    Keeps original URL first.
    """
    urls = [url]
    parsed = urlparse(url)

    # API fallback: export.arxiv.org -> arxiv.org
    if parsed.netloc == "export.arxiv.org" and parsed.path.startswith("/api/query"):
        alt = urlunparse(parsed._replace(netloc="arxiv.org"))
        if alt not in urls:
            urls.append(alt)

    return urls


def fetch_url(url: str, retries: int = 2, timeout: int = 30) -> str:
    """Fetch URL content as string with retries."""
    errors: List[str] = []
    saw_dns_error = False
    for candidate_url in _fallback_urls(url):
        req = Request(candidate_url, headers={"User-Agent": USER_AGENT})
        for attempt in range(retries + 1):
            try:
                with urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except (URLError, HTTPError, TimeoutError) as e:
                errors.append(f"{candidate_url} -> {e}")
                log.warning(
                    f"Attempt {attempt+1}/{retries+1} failed for {candidate_url}: {e}"
                )
                if _is_dns_error(e):
                    saw_dns_error = True
                    # DNS failures are not retryable in-process. Switch candidate host.
                    break
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))

    hint = (
        " DNS resolution failed for arXiv hosts. "
        "Check VPN/proxy/firewall, or set --api-base/--rss-base/--html-base to reachable endpoints."
    )
    dns_hint = hint if saw_dns_error else ""
    raise ConnectionError(
        f"Failed to fetch {url} via {len(_fallback_urls(url))} URL candidate(s).{dns_hint}\n"
        + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# Method 1: Arxiv Atom API (for date-range queries)
# ---------------------------------------------------------------------------
def fetch_api_daterange(
    categories: List[str],
    date_from: str,
    date_to: str,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    api_base: str = ARXIV_API_BASE,
) -> List[Dict]:
    """
    Query the arxiv API for papers submitted in [date_from, date_to].
    Dates are YYYYMMDD format.
    """
    papers = []
    total_chunks = _build_date_chunks(date_from, date_to, chunk_days)
    for cat in categories:
        category_papers = []
        log.info(
            f"API query for {cat}: {date_from}..{date_to} in {len(total_chunks)} chunk(s)"
        )

        for i, (chunk_from, chunk_to) in enumerate(total_chunks, start=1):
            log.info(
                f"  [{cat}] chunk {i}/{len(total_chunks)}: "
                f"submittedDate:[{chunk_from}* TO {chunk_to}*]"
            )
            try:
                chunk_papers = _fetch_api_daterange_chunk(
                    cat, chunk_from, chunk_to, api_base=api_base
                )
                category_papers.extend(chunk_papers)
            except Exception as e:
                if _is_dns_error(e):
                    raise ConnectionError(f"API DNS failure while fetching {cat}: {e}") from e
                log.warning(
                    f"  [{cat}] chunk {chunk_from}-{chunk_to} failed and will be skipped: {e}"
                )

            if i < len(total_chunks):
                time.sleep(API_DELAY)

        log.info(f"  [{cat}] collected {len(category_papers)} entries across chunks")
        papers.extend(category_papers)

        # Delay between categories
        if cat != categories[-1]:
            time.sleep(API_DELAY)

    return papers


def _build_date_chunks(date_from: str, date_to: str, chunk_days: int) -> List[Tuple[str, str]]:
    start_dt = datetime.strptime(date_from, "%Y%m%d")
    end_dt = datetime.strptime(date_to, "%Y%m%d")
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    chunk_days = max(1, chunk_days)
    chunks: List[Tuple[str, str]] = []
    cursor = start_dt

    while cursor <= end_dt:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_dt)
        chunks.append((cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def _fetch_api_daterange_chunk(
    cat: str,
    date_from: str,
    date_to: str,
    api_base: str = ARXIV_API_BASE,
) -> List[Dict]:
    papers = []
    query = f"cat:{cat}+AND+submittedDate:[{date_from}0000+TO+{date_to}2359]"
    start = 0
    total = None

    while total is None or start < total:
        params = urlencode({
            "search_query": query,
            "start": start,
            "max_results": MAX_RESULTS_PER_QUERY,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }, safe="+:[]")
        url = f"{api_base}?{params}"

        root = _fetch_atom_root(url)

        if total is None:
            total_el = root.find(f"{OPENSEARCH_NS}totalResults")
            total = int(total_el.text) if total_el is not None and total_el.text else 0
            log.info(f"    [{cat}] total in chunk: {total}")
            if total == 0:
                break

        entries = root.findall(f"{ATOM_NS}entry")
        if not entries:
            break

        for entry in entries:
            paper = _parse_api_entry(entry)
            if paper:
                papers.append(paper)

        start += len(entries)
        if start < total:
            time.sleep(API_DELAY)

    return papers


def _fetch_atom_root(url: str, retries: int = 3, timeout: int = 30) -> ET.Element:
    """Fetch and parse Atom XML with retries (helps against transient truncation/errors)."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            xml_text = fetch_url(url, retries=1, timeout=timeout)
            return ET.fromstring(xml_text)
        except Exception as e:
            last_error = e
            if _is_dns_error(e):
                break
            if attempt < retries:
                sleep_s = 2 * (attempt + 1)
                log.warning(
                    f"    Atom parse/fetch failed ({attempt+1}/{retries+1}); retrying in {sleep_s}s: {e}"
                )
                time.sleep(sleep_s)
    raise ConnectionError(f"Failed to fetch/parse Atom feed: {last_error}")


def _parse_api_entry(entry: ET.Element) -> Optional[Dict]:
    """Parse a single <entry> from the arxiv API Atom response."""
    try:
        # ID: e.g. http://arxiv.org/abs/2511.10616v1
        raw_id = entry.findtext(f"{ATOM_NS}id", "")
        arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
        # Strip version
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

        title = entry.findtext(f"{ATOM_NS}title", "")
        abstract = entry.findtext(f"{ATOM_NS}summary", "")

        authors = []
        for author_el in entry.findall(f"{ATOM_NS}author"):
            name = author_el.findtext(f"{ATOM_NS}name", "")
            if name:
                authors.append(name)

        categories = []
        primary_cat = ""
        prim_el = entry.find(f"{ARXIV_NS}primary_category")
        if prim_el is not None:
            primary_cat = prim_el.get("term", "")

        for cat_el in entry.findall(f"{ATOM_NS}category"):
            term = cat_el.get("term", "")
            if term:
                categories.append(term)

        published = entry.findtext(f"{ATOM_NS}published", "")
        updated = entry.findtext(f"{ATOM_NS}updated", "")
        comment = entry.findtext(f"{ARXIV_NS}comment", "")
        journal_ref = entry.findtext(f"{ARXIV_NS}journal_ref", "")
        doi = entry.findtext(f"{ARXIV_NS}doi", "")

        return make_paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            primary_category=primary_cat,
            published=published,
            updated=updated,
            comment=comment or "",
            journal_ref=journal_ref or "",
            doi=doi or "",
        )
    except Exception as e:
        log.warning(f"Failed to parse API entry: {e}")
        return None


# ---------------------------------------------------------------------------
# Method 2: RSS/Atom feed (for "today's new" papers)
# ---------------------------------------------------------------------------
def fetch_rss_today(categories: List[str], rss_base: str = ARXIV_RSS_BASE) -> List[Dict]:
    """
    Fetch today's new papers from the arxiv RSS/Atom feeds.
    These feeds contain exactly the daily announcement (new + cross-lists + replacements).
    We can combine multiple categories with '+'.
    """
    papers = []

    # Fetch categories in batches (arxiv supports combining with '+')
    cat_str = "+".join(categories)
    url = f"{rss_base}/{cat_str}"
    log.info(f"RSS feed: {url}")

    try:
        xml_text = fetch_url(url)
        root = ET.fromstring(xml_text)

        for entry in root.findall(f"{ATOM_NS}entry"):
            paper = _parse_rss_entry(entry)
            if paper:
                papers.append(paper)

        log.info(f"  RSS returned {len(papers)} entries")
    except Exception as e:
        log.warning(f"RSS feed failed: {e}")

    return papers


def _parse_rss_entry(entry: ET.Element) -> Optional[Dict]:
    """Parse a single <entry> from the arxiv RSS Atom feed."""
    try:
        # ID from <id> tag
        raw_id = entry.findtext(f"{ATOM_NS}id", "")
        arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

        title = entry.findtext(f"{ATOM_NS}title", "")
        abstract = entry.findtext(f"{ATOM_NS}summary", "")

        # Authors — RSS feeds use <author><name> or dc:creator
        authors = []
        for author_el in entry.findall(f"{ATOM_NS}author"):
            name = author_el.findtext(f"{ATOM_NS}name", "")
            if name:
                authors.append(name)

        # If no Atom authors, try to extract from summary (RSS feeds sometimes embed them)
        if not authors and abstract:
            # Some feeds put "Authors: X, Y, Z" in the description
            m = re.search(r"Authors?:\s*(.+?)(?:\n|<br|$)", abstract)
            if m:
                authors = [a.strip() for a in m.group(1).split(",")]

        categories = []
        for cat_el in entry.findall(f"{ATOM_NS}category"):
            term = cat_el.get("term", "")
            if term:
                categories.append(term)

        # Announce type from arxiv extension
        announce_type = "new"
        for child in entry:
            if "announce_type" in child.tag:
                announce_type = (child.text or "new").strip()

        published = entry.findtext(f"{ATOM_NS}published", "")
        updated = entry.findtext(f"{ATOM_NS}updated", "")

        return make_paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            published=published,
            updated=updated,
            announce_type=announce_type,
        )
    except Exception as e:
        log.warning(f"Failed to parse RSS entry: {e}")
        return None


# ---------------------------------------------------------------------------
# Method 3: HTML scraping fallback
# ---------------------------------------------------------------------------
class ArxivListParser(HTMLParser):
    """Parse arxiv /list/{cat}/new or /list/{cat}/recent HTML pages."""

    def __init__(self):
        super().__init__()
        self.papers = []
        self._current = {}
        self._in_title = False
        self._in_abstract = False
        self._in_authors = False
        self._in_subjects = False
        self._buffer = ""
        self._current_id = ""
        self._capture_abstract = False
        self._dd_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Detect arxiv ID from title links: /abs/XXXX.XXXXX
        if tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            if href.startswith("/abs/"):
                self._current_id = href.replace("/abs/", "").strip()

        # Title in <span class="descriptor">Title:</span> followed by content
        cls = attrs_dict.get("class", "")
        if tag == "span" and "descriptor" in cls:
            self._buffer = ""

        # List-title contains the title text
        if tag == "div" and "list-title" in cls:
            self._in_title = True
            self._buffer = ""

        # Authors
        if tag == "div" and "list-authors" in cls:
            self._in_authors = True
            self._buffer = ""

        # Abstract / mathjax
        if tag == "p" and "mathjax" in cls:
            self._in_abstract = True
            self._buffer = ""

        # Subjects line
        if tag == "span" and "primary-subject" in cls:
            self._in_subjects = True
            self._buffer = ""

    def handle_endtag(self, tag):
        if tag == "div" and self._in_title:
            self._in_title = False
            title = self._buffer.strip()
            # Remove "Title: " prefix
            title = re.sub(r"^Title:\s*", "", title)
            if self._current_id:
                self._current["arxiv_id"] = self._current_id
                self._current["title"] = title

        if tag == "div" and self._in_authors:
            self._in_authors = False
            authors_text = self._buffer.strip()
            authors_text = re.sub(r"^Authors:\s*", "", authors_text)
            authors = [a.strip() for a in authors_text.split(",") if a.strip()]
            self._current["authors"] = authors

        if tag == "p" and self._in_abstract:
            self._in_abstract = False
            self._current["abstract"] = self._buffer.strip()

            # Emit paper if we have the minimum fields
            if self._current.get("arxiv_id") and self._current.get("title"):
                self.papers.append(make_paper(
                    arxiv_id=self._current.get("arxiv_id", ""),
                    title=self._current.get("title", ""),
                    authors=self._current.get("authors", []),
                    abstract=self._current.get("abstract", ""),
                    categories=self._current.get("categories", []),
                ))
                self._current = {}
                self._current_id = ""

    def handle_data(self, data):
        if self._in_title or self._in_authors or self._in_abstract or self._in_subjects:
            self._buffer += data


def fetch_html_listing(
    categories: List[str],
    page: str = "new",
    html_base: str = ARXIV_HTML_BASE,
) -> List[Dict]:
    """
    Scrape arxiv /list/{cat}/{page} HTML pages.
    page: 'new', 'recent', 'pastweek', or 'YYMM' (e.g., '2511')
    """
    papers = []

    for cat in categories:
        url = f"{html_base}/{cat}/{page}"
        log.info(f"HTML scrape: {url}")

        try:
            html_text = fetch_url(url)
            parser = ArxivListParser()
            parser.feed(html_text)
            log.info(f"  Parsed {len(parser.papers)} papers from HTML for {cat}")
            papers.extend(parser.papers)
        except Exception as e:
            log.warning(f"HTML scrape failed for {cat}: {e}")

        if cat != categories[-1]:
            time.sleep(1)  # be polite

    return papers


# ---------------------------------------------------------------------------
# Deduplication & filtering
# ---------------------------------------------------------------------------
def deduplicate(papers: List[Dict]) -> List[Dict]:
    """Remove duplicate papers by arxiv_id, keeping the first occurrence."""
    seen = set()
    unique = []
    for p in papers:
        key = re.sub(r"v\d+$", "", p["arxiv_id"])
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def filter_new_only(papers: List[Dict]) -> List[Dict]:
    """Keep only new submissions (not replacements)."""
    return [
        p for p in papers
        if p.get("announce_type", "new") in ("new", "cross", "cross-list", "")
    ]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def parse_period(period: str) -> Tuple[str, str, str]:
    """
    Parse period argument into (mode, date_from, date_to).
    mode: 'today' | 'daterange' | 'html_page'
    Returns YYYYMMDD strings for dates.
    """
    period = period.strip().lower()

    if period == "today":
        return ("today", "", "")

    if period == "week" or period == "pastweek":
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        return ("daterange", week_ago.strftime("%Y%m%d"), today.strftime("%Y%m%d"))

    if period in ("month", "pastmonth", "30d"):
        today = datetime.now()
        month_ago = today - timedelta(days=30)
        return ("daterange", month_ago.strftime("%Y%m%d"), today.strftime("%Y%m%d"))

    m_days = re.match(r"^(\d{1,3})d$", period)
    if m_days:
        days = max(1, int(m_days.group(1)))
        today = datetime.now()
        start = today - timedelta(days=days)
        return ("daterange", start.strftime("%Y%m%d"), today.strftime("%Y%m%d"))

    if period == "recent":
        return ("html_page", "recent", "")

    # Single date: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", period):
        d = period.replace("-", "")
        return ("daterange", d, d)

    # Date range: YYYY-MM-DD:YYYY-MM-DD
    if ":" in period:
        parts = period.split(":")
        if len(parts) == 2:
            d1 = _normalize_ymd(parts[0].strip())
            d2 = _normalize_ymd(parts[1].strip())
            if d1 and d2:
                return ("daterange", d1, d2)

    # Month shorthand: YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", period):
        month_start = datetime.strptime(period + "-01", "%Y-%m-%d")
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        month_end = next_month - timedelta(days=1)
        return (
            "daterange",
            month_start.strftime("%Y%m%d"),
            month_end.strftime("%Y%m%d"),
        )

    # Fallback: try as html page identifier
    return ("html_page", period, "")


def _normalize_ymd(text: str) -> str:
    token = text.replace("-", "")
    if not re.match(r"^\d{8}$", token):
        return ""
    try:
        datetime.strptime(token, "%Y%m%d")
    except ValueError:
        return ""
    return token


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def fetch_papers(
    categories: List[str],
    period: str = "today",
    include_replacements: bool = False,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    api_base: str = ARXIV_API_BASE,
    rss_base: str = ARXIV_RSS_BASE,
    html_base: str = ARXIV_HTML_BASE,
) -> List[Dict]:
    """
    Fetch papers for the given categories and period.
    Tries API/RSS first, falls back to HTML scraping.
    """
    mode, date_from, date_to = parse_period(period)
    papers = []

    if mode == "today":
        # Try RSS feed first (best for today's papers)
        log.info("=== Trying RSS feed for today's papers ===")
        try:
            papers = fetch_rss_today(categories, rss_base=rss_base)
        except Exception as e:
            log.warning(f"RSS failed: {e}")

        # Fallback to HTML if RSS returned nothing
        if not papers:
            log.info("=== RSS empty/failed, falling back to HTML scraping ===")
            try:
                papers = fetch_html_listing(categories, "new", html_base=html_base)
            except Exception as e:
                log.warning(f"HTML scrape also failed: {e}")

    elif mode == "daterange":
        # Use API for date range queries
        log.info(f"=== Using API for date range {date_from} to {date_to} ===")
        try:
            papers = fetch_api_daterange(
                categories, date_from, date_to, chunk_days=chunk_days, api_base=api_base
            )
        except Exception as e:
            log.warning(f"API failed: {e}")

        # Fallback to HTML for recent/pastweek
        if not papers:
            log.info("=== API empty/failed, falling back to HTML ===")
            try:
                papers = fetch_html_listing(categories, "recent", html_base=html_base)
            except Exception as e:
                log.warning(f"HTML fallback also failed: {e}")

    elif mode == "html_page":
        # Direct HTML page fetch
        log.info(f"=== Fetching HTML page: {date_from} ===")
        papers = fetch_html_listing(categories, date_from, html_base=html_base)

    # Post-process
    papers = deduplicate(papers)
    if not include_replacements:
        papers = filter_new_only(papers)

    log.info(f"=== Total unique papers: {len(papers)} ===")
    return papers


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Fetch arxiv paper metadata for given categories and time period."
    )
    parser.add_argument(
        "--categories", "-c",
        nargs="+",
        help="Arxiv categories (e.g., astro-ph.CO astro-ph.GA)",
    )
    parser.add_argument(
        "--prefs", "-p",
        help="Path to arxiv_preferences.json (reads categories from it)",
    )
    parser.add_argument(
        "--storage-dir",
        help="Storage root override (default: ARXIV_DIGEST_HOME, XDG_DATA_HOME/arxiv-digest, or ~/.claude/arxiv-digest)",
    )
    parser.add_argument(
        "--period", "-t",
        default="today",
        help="Time period: 'today', 'week', 'month', '30d', 'Nd', 'recent', 'YYYY-MM-DD', 'YYYY-MM', or 'YYYY-MM-DD:YYYY-MM-DD'",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help="Date-range API chunk size in days (smaller is more reliable for long periods; default: 7)",
    )
    parser.add_argument(
        "--api-base",
        default=ARXIV_API_BASE,
        help=f"Arxiv API base URL (default: {ARXIV_API_BASE})",
    )
    parser.add_argument(
        "--rss-base",
        default=ARXIV_RSS_BASE,
        help=f"Arxiv RSS base URL (default: {ARXIV_RSS_BASE})",
    )
    parser.add_argument(
        "--html-base",
        default=ARXIV_HTML_BASE,
        help=f"Arxiv HTML listing base URL (default: {ARXIV_HTML_BASE})",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--include-replacements",
        action="store_true",
        help="Include replacement papers (default: new + cross-list only)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress log messages (only output JSON)",
    )

    args = parser.parse_args()
    paths = get_storage_paths(args.storage_dir)

    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Resolve categories
    categories = args.categories
    prefs_path = args.prefs
    if not prefs_path and paths.prefs.exists():
        prefs_path = str(paths.prefs)

    if not categories and prefs_path:
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
            categories = prefs.get("arxiv_categories", [])
            log.info(f"Loaded categories from prefs: {categories} ({prefs_path})")
        except Exception as e:
            log.error(f"Failed to read preferences: {e}")
            sys.exit(1)

    if not categories:
        log.error("No categories specified. Use --categories, --prefs, or create default prefs in storage.")
        sys.exit(1)

    # Fetch
    papers = fetch_papers(
        categories=categories,
        period=args.period,
        include_replacements=args.include_replacements,
        chunk_days=args.chunk_days,
        api_base=args.api_base,
        rss_base=args.rss_base,
        html_base=args.html_base,
    )

    # Output
    output_json = json.dumps(papers, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        log.info(f"Wrote {len(papers)} papers to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
