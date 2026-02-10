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
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote_plus, urlencode
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARXIV_API_BASE = "http://export.arxiv.org/api/query"
ARXIV_RSS_BASE = "https://rss.arxiv.org/atom"
ARXIV_HTML_BASE = "https://arxiv.org/list"
API_DELAY = 3.1  # seconds between API requests (arxiv asks for 3s)
MAX_RESULTS_PER_QUERY = 200  # API max per page
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
def fetch_url(url: str, retries: int = 2, timeout: int = 30) -> str:
    """Fetch URL content as string with retries."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as e:
            log.warning(f"Attempt {attempt+1}/{retries+1} failed for {url}: {e}")
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise ConnectionError(f"Failed to fetch {url} after {retries+1} attempts")


# ---------------------------------------------------------------------------
# Method 1: Arxiv Atom API (for date-range queries)
# ---------------------------------------------------------------------------
def fetch_api_daterange(
    categories: List[str], date_from: str, date_to: str
) -> List[Dict]:
    """
    Query the arxiv API for papers submitted in [date_from, date_to].
    Dates are YYYYMMDD format.
    """
    papers = []
    for cat in categories:
        log.info(f"API query: cat:{cat} submittedDate:[{date_from}* TO {date_to}*]")
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
            url = f"{ARXIV_API_BASE}?{params}"
            log.info(f"  Fetching start={start} ...")

            xml_text = fetch_url(url)
            root = ET.fromstring(xml_text)

            # Parse total results
            if total is None:
                total_el = root.find(f"{OPENSEARCH_NS}totalResults")
                total = int(total_el.text) if total_el is not None else 0
                log.info(f"  Total results for {cat}: {total}")
                if total == 0:
                    break

            # Parse entries
            entries = root.findall(f"{ATOM_NS}entry")
            if not entries:
                break

            for entry in entries:
                paper = _parse_api_entry(entry)
                if paper:
                    papers.append(paper)

            start += len(entries)

            # Rate limit
            if start < total:
                time.sleep(API_DELAY)

        # Delay between categories
        if cat != categories[-1]:
            time.sleep(API_DELAY)

    return papers


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
def fetch_rss_today(categories: List[str]) -> List[Dict]:
    """
    Fetch today's new papers from the arxiv RSS/Atom feeds.
    These feeds contain exactly the daily announcement (new + cross-lists + replacements).
    We can combine multiple categories with '+'.
    """
    papers = []

    # Fetch categories in batches (arxiv supports combining with '+')
    cat_str = "+".join(categories)
    url = f"{ARXIV_RSS_BASE}/{cat_str}"
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
    categories: List[str], page: str = "new"
) -> List[Dict]:
    """
    Scrape arxiv /list/{cat}/{page} HTML pages.
    page: 'new', 'recent', 'pastweek', or 'YYMM' (e.g., '2511')
    """
    papers = []

    for cat in categories:
        url = f"{ARXIV_HTML_BASE}/{cat}/{page}"
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
            d1 = parts[0].strip().replace("-", "")
            d2 = parts[1].strip().replace("-", "")
            return ("daterange", d1, d2)

    # Fallback: try as html page identifier
    return ("html_page", period, "")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def fetch_papers(
    categories: List[str],
    period: str = "today",
    include_replacements: bool = False,
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
            papers = fetch_rss_today(categories)
        except Exception as e:
            log.warning(f"RSS failed: {e}")

        # Fallback to HTML if RSS returned nothing
        if not papers:
            log.info("=== RSS empty/failed, falling back to HTML scraping ===")
            try:
                papers = fetch_html_listing(categories, "new")
            except Exception as e:
                log.warning(f"HTML scrape also failed: {e}")

    elif mode == "daterange":
        # Use API for date range queries
        log.info(f"=== Using API for date range {date_from} to {date_to} ===")
        try:
            papers = fetch_api_daterange(categories, date_from, date_to)
        except Exception as e:
            log.warning(f"API failed: {e}")

        # Fallback to HTML for recent/pastweek
        if not papers:
            log.info("=== API empty/failed, falling back to HTML ===")
            try:
                papers = fetch_html_listing(categories, "recent")
            except Exception as e:
                log.warning(f"HTML fallback also failed: {e}")

    elif mode == "html_page":
        # Direct HTML page fetch
        log.info(f"=== Fetching HTML page: {date_from} ===")
        papers = fetch_html_listing(categories, date_from)

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
        "--period", "-t",
        default="today",
        help="Time period: 'today', 'week', 'recent', 'YYYY-MM-DD', or 'YYYY-MM-DD:YYYY-MM-DD'",
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

    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Resolve categories
    categories = args.categories
    if not categories and args.prefs:
        try:
            with open(args.prefs) as f:
                prefs = json.load(f)
            categories = prefs.get("arxiv_categories", [])
            log.info(f"Loaded categories from prefs: {categories}")
        except Exception as e:
            log.error(f"Failed to read preferences: {e}")
            sys.exit(1)

    if not categories:
        log.error("No categories specified. Use --categories or --prefs.")
        sys.exit(1)

    # Fetch
    papers = fetch_papers(
        categories=categories,
        period=args.period,
        include_replacements=args.include_replacements,
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
