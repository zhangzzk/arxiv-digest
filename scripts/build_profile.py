#!/usr/bin/env python3
"""
build_profile.py — Build a researcher profile and collaboration network
from arxiv/ADS metadata.

Given a researcher's name (and optionally ORCID or arxiv author ID), this script:
1. Finds their papers via the arxiv API
2. Extracts co-authors and builds a collaboration network
3. Extracts frequently cited/referenced topics
4. Outputs a structured researcher profile JSON

Usage:
    python3 build_profile.py --name "Jane Doe" --output profile.json
    python3 build_profile.py --name "Jane Doe" --orcid 0000-0001-2345-6789
    python3 build_profile.py --name "Jane Doe" --arxiv-ids 2301.00001 2305.12345
    python3 build_profile.py --update profile.json  # refresh an existing profile

Output: researcher_profile.json (see schema in references/profile-schema.md)

Dependencies: Python 3.8+ standard library only
"""

import argparse
import json
import sys
import re
import time
import logging
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from typing import List, Dict, Optional, Set, Tuple

from storage_paths import get_storage_paths, update_user_record

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ARXIV_API_BASE = "http://export.arxiv.org/api/query"
API_DELAY = 3.1
MAX_RESULTS = 200
USER_AGENT = "arxiv-digest-skill/1.0"

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def fetch_url(url: str, retries: int = 2, timeout: int = 30) -> str:
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
# Arxiv API: find papers by author
# ---------------------------------------------------------------------------
def search_author_papers(
    author_name: str,
    max_papers: int = 300,
    categories: Optional[List[str]] = None,
) -> List[Dict]:
    """Search arxiv for papers by an author. Returns list of paper dicts."""
    papers = []
    # Build query: author name, optionally restricted to categories
    # Arxiv author search uses au:"Last First" format
    query = f'au:"{author_name}"'
    if categories:
        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        query = f'{query} AND ({cat_query})'

    start = 0
    total = None

    while total is None or start < min(total, max_papers):
        params = urlencode({
            "search_query": query,
            "start": start,
            "max_results": min(MAX_RESULTS, max_papers - start),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        url = f"{ARXIV_API_BASE}?{params}"
        log.info(f"  Fetching author papers start={start} ...")

        xml_text = fetch_url(url)
        root = ET.fromstring(xml_text)

        if total is None:
            total_el = root.find(f"{OPENSEARCH_NS}totalResults")
            total = int(total_el.text) if total_el is not None else 0
            log.info(f"  Total papers found for '{author_name}': {total}")
            if total == 0:
                break

        entries = root.findall(f"{ATOM_NS}entry")
        if not entries:
            break

        for entry in entries:
            paper = _parse_entry(entry)
            if paper:
                papers.append(paper)

        start += len(entries)
        if start < min(total, max_papers):
            time.sleep(API_DELAY)

    return papers


def fetch_papers_by_ids(arxiv_ids: List[str]) -> List[Dict]:
    """Fetch specific papers by their arxiv IDs."""
    papers = []
    # API supports comma-separated id_list
    batch_size = 50
    for i in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[i:i + batch_size]
        id_list = ",".join(batch)
        params = urlencode({"id_list": id_list, "max_results": len(batch)})
        url = f"{ARXIV_API_BASE}?{params}"
        log.info(f"  Fetching batch of {len(batch)} papers by ID ...")

        xml_text = fetch_url(url)
        root = ET.fromstring(xml_text)

        for entry in root.findall(f"{ATOM_NS}entry"):
            paper = _parse_entry(entry)
            if paper:
                papers.append(paper)

        if i + batch_size < len(arxiv_ids):
            time.sleep(API_DELAY)

    return papers


def _parse_entry(entry: ET.Element) -> Optional[Dict]:
    """Parse an arxiv API entry into a paper dict."""
    try:
        raw_id = entry.findtext(f"{ATOM_NS}id", "")
        arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

        title = " ".join(entry.findtext(f"{ATOM_NS}title", "").split())
        abstract = " ".join(entry.findtext(f"{ATOM_NS}summary", "").split())

        authors = []
        for author_el in entry.findall(f"{ATOM_NS}author"):
            name = author_el.findtext(f"{ATOM_NS}name", "")
            if name:
                authors.append(name)

        categories = []
        for cat_el in entry.findall(f"{ATOM_NS}category"):
            term = cat_el.get("term", "")
            if term:
                categories.append(term)

        primary_cat = ""
        prim_el = entry.find(f"{ARXIV_NS}primary_category")
        if prim_el is not None:
            primary_cat = prim_el.get("term", "")

        published = entry.findtext(f"{ATOM_NS}published", "")
        comment = entry.findtext(f"{ARXIV_NS}comment", "") or ""

        return {
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
            "primary_category": primary_cat,
            "published": published,
            "comment": comment,
        }
    except Exception as e:
        log.warning(f"Failed to parse entry: {e}")
        return None


# ---------------------------------------------------------------------------
# Network builder
# ---------------------------------------------------------------------------
def build_network(
    papers: List[Dict],
    user_name: str,
) -> Dict:
    """
    Build a collaboration network from a list of papers.

    Returns:
        {
            "coauthors": {name: {"count": N, "last_year": YYYY, "papers": [...]}},
            "coauthor_rank": [name, ...],  # sorted by frequency
            "active_coauthors": [name, ...],  # collaborated in last 3 years
            "topic_keywords": {keyword: count},
            "active_categories": {cat: count},
            "publication_years": {year: count},
        }
    """
    coauthors = defaultdict(lambda: {"count": 0, "last_year": 0, "papers": []})
    topic_words = Counter()
    category_counts = Counter()
    year_counts = Counter()

    # Normalize user name for matching
    user_name_lower = user_name.lower().strip()
    user_name_parts = set(user_name_lower.split())

    for paper in papers:
        # Extract year
        year = ""
        if paper.get("published"):
            m = re.match(r"(\d{4})", paper["published"])
            if m:
                year = m.group(1)
        if not year and paper.get("arxiv_id"):
            m = re.match(r"(\d{2})\d{2}\.", paper["arxiv_id"])
            if m:
                year = f"20{m.group(1)}"

        if year:
            year_counts[year] += 1

        # Categories
        for cat in paper.get("categories", []):
            category_counts[cat] += 1

        # Co-authors (everyone except the user)
        for author in paper.get("authors", []):
            author_lower = author.lower().strip()
            author_parts = set(author_lower.split())

            # Skip self — fuzzy match on name parts
            if _is_same_person(user_name_lower, user_name_parts, author_lower, author_parts):
                continue

            coauthors[author]["count"] += 1
            coauthors[author]["papers"].append(paper.get("arxiv_id", ""))
            if year:
                coauthors[author]["last_year"] = max(
                    coauthors[author]["last_year"], int(year)
                )

        # Extract topic keywords from title
        title_words = _extract_keywords(paper.get("title", ""))
        topic_words.update(title_words)

        # Also from abstract (lighter weight)
        abstract_words = _extract_keywords(paper.get("abstract", ""))
        for w in abstract_words:
            topic_words[w] += 0.3  # lower weight for abstract

    # Sort coauthors by frequency
    coauthor_rank = sorted(coauthors.keys(), key=lambda x: coauthors[x]["count"], reverse=True)

    # Active coauthors (last 3 years)
    current_year = datetime.now().year
    active_coauthors = [
        name for name in coauthor_rank
        if coauthors[name]["last_year"] >= current_year - 3
    ]

    # Clean up topic keywords — keep top 50
    top_topics = {k: round(v, 1) for k, v in topic_words.most_common(50)}

    # Truncate paper lists in coauthor data for storage
    coauthor_data = {}
    for name in coauthor_rank[:100]:  # keep top 100
        data = coauthors[name]
        coauthor_data[name] = {
            "count": data["count"],
            "last_year": data["last_year"],
            "papers": data["papers"][:10],  # keep up to 10 paper IDs
        }

    return {
        "coauthors": coauthor_data,
        "coauthor_rank": coauthor_rank[:100],
        "active_coauthors": active_coauthors[:50],
        "topic_keywords": top_topics,
        "active_categories": dict(category_counts.most_common(20)),
        "publication_years": dict(sorted(year_counts.items())),
    }


def _is_same_person(
    name1_lower: str, name1_parts: Set[str],
    name2_lower: str, name2_parts: Set[str],
) -> bool:
    """Fuzzy check if two author names refer to the same person."""
    # Exact match
    if name1_lower == name2_lower:
        return True

    # Check if last names match and at least one first-name initial matches
    # This handles "J. Smith" vs "John Smith" vs "Jane Smith" (imperfect but useful)
    if len(name1_parts) >= 2 and len(name2_parts) >= 2:
        # Get last name (last token)
        parts1 = name1_lower.split()
        parts2 = name2_lower.split()
        if parts1[-1] == parts2[-1]:  # same last name
            # Check first name/initial overlap
            first1 = parts1[0].rstrip(".")
            first2 = parts2[0].rstrip(".")
            if first1 == first2:
                return True
            if len(first1) == 1 and first2.startswith(first1):
                return True
            if len(first2) == 1 and first1.startswith(first2):
                return True

    return False


# Stop words for keyword extraction
_STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "with", "from",
    "by", "as", "it", "its", "this", "that", "these", "those", "we",
    "our", "us", "their", "they", "them", "which", "what", "how", "when",
    "where", "who", "will", "can", "may", "using", "via", "between",
    "into", "through", "during", "before", "after", "above", "below",
    "up", "down", "new", "first", "two", "three", "one", "based",
    "study", "analysis", "results", "data", "model", "method", "approach",
    "paper", "show", "find", "also", "than", "more", "most", "not", "no",
    "but", "if", "about", "each", "all", "both", "do", "does", "did",
    "has", "have", "had", "such", "only", "very", "just", "over", "under",
    "then", "so", "well", "here", "there", "some", "any", "other",
}


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text."""
    # Tokenize, lowercase, remove punctuation
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", text.lower())
    # Filter stop words and short words
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    return keywords


# ---------------------------------------------------------------------------
# Second-degree network (co-authors of co-authors)
# ---------------------------------------------------------------------------
def expand_network_second_degree(
    network: Dict,
    top_n: int = 10,
    max_papers_per_coauthor: int = 50,
) -> Dict:
    """
    For the top N most frequent co-authors, fetch THEIR recent papers
    and extract their co-authors. This gives us the 2nd-degree network.

    This is expensive (many API calls), so only do it for the closest collaborators.
    Returns an updated network dict with "second_degree" field.
    """
    second_degree = Counter()
    top_coauthors = network.get("coauthor_rank", [])[:top_n]

    for coauthor_name in top_coauthors:
        log.info(f"Expanding network for co-author: {coauthor_name}")
        try:
            coauthor_papers = search_author_papers(
                coauthor_name,
                max_papers=max_papers_per_coauthor,
            )
            for paper in coauthor_papers:
                for author in paper.get("authors", []):
                    author_lower = author.lower().strip()
                    # Skip the co-author themselves
                    if _is_same_person(
                        coauthor_name.lower(), set(coauthor_name.lower().split()),
                        author_lower, set(author_lower.split()),
                    ):
                        continue
                    second_degree[author] += 1
            time.sleep(API_DELAY)
        except Exception as e:
            log.warning(f"Failed to expand for {coauthor_name}: {e}")

    # Remove people already in 1st degree
    first_degree = set(network.get("coauthor_rank", []))
    second_only = {
        name: count for name, count in second_degree.most_common(200)
        if name not in first_degree
    }

    network["second_degree"] = dict(list(second_only.items())[:100])
    network["second_degree_rank"] = list(second_only.keys())[:100]

    return network


# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------
def build_profile(
    user_name: str,
    papers: List[Dict],
    orcid: str = "",
    affiliation: str = "",
    homepage: str = "",
    expand_second_degree: bool = False,
) -> Dict:
    """Build a complete researcher profile."""
    log.info(f"Building profile for: {user_name}")
    log.info(f"  Papers found: {len(papers)}")

    network = build_network(papers, user_name)

    if expand_second_degree and network.get("coauthor_rank"):
        log.info("Expanding to 2nd-degree network...")
        network = expand_network_second_degree(network)

    # Extract the user's own arxiv IDs
    own_paper_ids = [p["arxiv_id"] for p in papers]

    # Determine primary research categories
    cat_counts = network.get("active_categories", {})
    primary_categories = [
        cat for cat, _ in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
    ][:6]

    profile = {
        "version": 1,
        "researcher": {
            "name": user_name,
            "orcid": orcid,
            "affiliation": affiliation,
            "homepage": homepage,
        },
        "publications": {
            "total_count": len(papers),
            "paper_ids": own_paper_ids[:200],
            "recent_papers": [
                {
                    "arxiv_id": p["arxiv_id"],
                    "title": p["title"],
                    "year": re.match(r"(\d{4})", p.get("published", "")).group(1)
                        if p.get("published") and re.match(r"(\d{4})", p["published"])
                        else "",
                }
                for p in papers[:20]  # most recent 20
            ],
            "primary_categories": primary_categories,
            "publication_years": network.get("publication_years", {}),
        },
        "network": {
            "coauthors": network.get("coauthors", {}),
            "coauthor_rank": network.get("coauthor_rank", []),
            "active_coauthors": network.get("active_coauthors", []),
            "second_degree": network.get("second_degree", {}),
            "second_degree_rank": network.get("second_degree_rank", []),
        },
        "research_fingerprint": {
            "topic_keywords": network.get("topic_keywords", {}),
            "active_categories": network.get("active_categories", {}),
        },
        "built_at": datetime.now().isoformat(),
    }

    return profile


def update_profile(existing_profile: Dict) -> Dict:
    """Refresh an existing profile by re-fetching papers."""
    researcher = existing_profile.get("researcher", {})
    name = researcher.get("name", "")
    if not name:
        log.error("Existing profile has no researcher name")
        sys.exit(1)

    categories = existing_profile.get("publications", {}).get("primary_categories", [])

    log.info(f"Updating profile for: {name}")
    papers = search_author_papers(name, categories=categories or None)

    return build_profile(
        user_name=name,
        papers=papers,
        orcid=researcher.get("orcid", ""),
        affiliation=researcher.get("affiliation", ""),
        homepage=researcher.get("homepage", ""),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Build a researcher profile and collaboration network from arxiv."
    )
    parser.add_argument("--name", "-n", help="Researcher full name (e.g., 'Jane Doe')")
    parser.add_argument("--orcid", help="ORCID identifier")
    parser.add_argument("--affiliation", "-a", help="Current affiliation")
    parser.add_argument("--homepage", help="Personal/group homepage URL")
    parser.add_argument(
        "--arxiv-ids", nargs="+",
        help="Known arxiv paper IDs (supplements author search)",
    )
    parser.add_argument(
        "--categories", "-c", nargs="+",
        help="Restrict author search to these categories",
    )
    parser.add_argument(
        "--expand-network", action="store_true",
        help="Also build 2nd-degree network (slower, more API calls)",
    )
    parser.add_argument(
        "--update", "-u",
        help="Path to existing profile.json to refresh",
    )
    parser.add_argument(
        "--storage-dir",
        help="Storage root override (default: ARXIV_DIGEST_HOME, XDG_DATA_HOME/arxiv-digest, or ~/.claude/arxiv-digest)",
    )
    parser.add_argument("--output", "-o",
                        help="Output file path (default: storage/researcher_profile.json, or --update path in update mode)")
    parser.add_argument("--quiet", "-q", action="store_true")

    args = parser.parse_args()
    paths = get_storage_paths(args.storage_dir)

    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Update mode
    if args.update:
        output_path = Path(args.output).expanduser().resolve() if args.output else Path(args.update).expanduser().resolve()
        with open(args.update) as f:
            existing = json.load(f)
        profile = update_profile(existing)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        update_user_record(paths, profile_path=output_path)
        log.info(f"Updated profile written to {output_path}")
        return

    # Build mode
    if not args.name:
        log.error("--name is required (or use --update to refresh an existing profile)")
        sys.exit(1)

    # Fetch papers
    try:
        papers = search_author_papers(
            args.name,
            categories=args.categories,
        )
    except ConnectionError as e:
        log.error(f"Network error: {e}")
        log.error("Cannot reach arxiv API. Check your network connection.")
        papers = []

    # Supplement with specific arxiv IDs if provided
    if args.arxiv_ids:
        known_ids = {p["arxiv_id"] for p in papers}
        extra_ids = [aid for aid in args.arxiv_ids if aid not in known_ids]
        if extra_ids:
            try:
                extra_papers = fetch_papers_by_ids(extra_ids)
                papers.extend(extra_papers)
            except ConnectionError as e:
                log.warning(f"Could not fetch extra papers: {e}")

    if not papers:
        log.warning(f"No papers found for '{args.name}'. "
                     "Try providing --arxiv-ids or adjusting the name format.")

    profile = build_profile(
        user_name=args.name,
        papers=papers,
        orcid=args.orcid or "",
        affiliation=args.affiliation or "",
        homepage=args.homepage or "",
        expand_second_degree=args.expand_network,
    )

    output_path = Path(args.output).expanduser().resolve() if args.output else paths.profile
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    update_user_record(paths, profile_path=output_path)

    log.info(f"Profile written to {output_path}")
    log.info(f"  Papers: {profile['publications']['total_count']}")
    log.info(f"  Co-authors: {len(profile['network']['coauthor_rank'])}")
    log.info(f"  Active co-authors: {len(profile['network']['active_coauthors'])}")
    if profile['network'].get('second_degree_rank'):
        log.info(f"  2nd-degree contacts: {len(profile['network']['second_degree_rank'])}")


if __name__ == "__main__":
    main()
