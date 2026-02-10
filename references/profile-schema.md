# Researcher Profile Schema

## Overview

The researcher profile captures who the user is, what they've published, and who they work with. This powers network-aware paper ranking — papers by co-authors, citing the user's work, or from the user's extended research community get a relevance boost.

## Full Schema (v1)

```json
{
  "version": 1,
  "researcher": {
    "name": "Jane Doe",
    "orcid": "0000-0001-2345-6789",
    "affiliation": "University of Somewhere",
    "homepage": "https://janedoe.github.io"
  },
  "publications": {
    "total_count": 42,
    "paper_ids": ["2301.00001", "2205.12345", "..."],
    "recent_papers": [
      {"arxiv_id": "2301.00001", "title": "My Latest Paper", "year": "2023"}
    ],
    "primary_categories": ["astro-ph.CO", "astro-ph.IM"],
    "publication_years": {"2019": 3, "2020": 5, "2021": 8}
  },
  "network": {
    "coauthors": {
      "Alice Smith": {"count": 12, "last_year": 2025, "papers": ["2501.00001"]},
      "Bob Jones": {"count": 5, "last_year": 2024, "papers": ["2401.00002"]}
    },
    "coauthor_rank": ["Alice Smith", "Bob Jones", "..."],
    "active_coauthors": ["Alice Smith", "Bob Jones"],
    "second_degree": {
      "Charlie Brown": 8,
      "Diana Prince": 5
    },
    "second_degree_rank": ["Charlie Brown", "Diana Prince"]
  },
  "research_fingerprint": {
    "topic_keywords": {"cosmology": 25.0, "inference": 18.3, "lensing": 15.1},
    "active_categories": {"astro-ph.CO": 30, "astro-ph.IM": 12}
  },
  "built_at": "2025-11-14T10:30:00"
}
```

## Field Descriptions

### `researcher`
Basic identity information. The `name` is used for arxiv author searches and for self-identification in co-author lists. ORCID disambiguates common names.

### `publications`
The user's own publication record:
- `paper_ids` — all known arxiv IDs (up to 200)
- `recent_papers` — the 20 most recent, with titles for display
- `primary_categories` — derived from where they publish most
- `publication_years` — activity over time

### `network`
The collaboration graph:
- `coauthors` — 1st-degree: people who have co-authored papers with the user. Includes collaboration frequency, last active year, and sample paper IDs.
- `coauthor_rank` — sorted by frequency (most frequent first)
- `active_coauthors` — subset who collaborated in the last 3 years
- `second_degree` — people who co-author with the user's co-authors but not directly with the user. These represent the extended research community.
- `second_degree_rank` — sorted by frequency

### `research_fingerprint`
Derived from the user's publication titles and abstracts:
- `topic_keywords` — weighted keyword frequencies
- `active_categories` — arxiv categories they publish in

## How the Profile Feeds Into Scoring

When ranking daily papers, the profile provides several scoring signals:

### Author-based signals

| Signal | Boost level | Description |
|--------|-------------|-------------|
| Paper by active co-author | **Strong** | Someone you currently work with posted a paper |
| Paper by any co-author | **Moderate** | Past collaborator's new work |
| Paper by 2nd-degree contact | **Mild** | Someone in your extended network |
| Paper cites user's work | **Strong** | Direct engagement with your research |

### Topic-based signals

The `research_fingerprint.topic_keywords` provides a richer interest model than manually specified keywords. It captures the actual vocabulary of the user's papers. Papers whose titles/abstracts share high-weight keywords get a boost.

### Category-based signals

The `publications.primary_categories` tells us where the user publishes. Papers in these categories are more likely relevant. Cross-lists between the user's categories are especially interesting.

## Building the Profile

### Initial setup
```bash
python3 scripts/build_profile.py \
    --name "Jane Doe" \
    --affiliation "University of Somewhere" \
    --categories astro-ph.CO astro-ph.IM \
    --output researcher_profile.json
```

### With known papers (helps disambiguation)
```bash
python3 scripts/build_profile.py \
    --name "Jane Doe" \
    --arxiv-ids 2301.00001 2205.12345 2109.99999 \
    --output researcher_profile.json
```

### With 2nd-degree expansion (slower)
```bash
python3 scripts/build_profile.py \
    --name "Jane Doe" \
    --expand-network \
    --output researcher_profile.json
```

### Refresh an existing profile
```bash
python3 scripts/build_profile.py \
    --update researcher_profile.json \
    --output researcher_profile.json
```

## Integration with Preferences

The researcher profile and the preference file are complementary:
- **Profile** = who you are, derived automatically from your publications
- **Preferences** = what you want to read, learned from your feedback

The SKILL.md describes how to combine both for scoring. In brief:
1. Load both files
2. Score papers using preference keywords (as before)
3. Add network-based boosts from the profile
4. Papers by active co-authors jump to the top of the relevant tier
5. 2nd-degree papers get a mild boost (they're "from your neighborhood")

## Name Disambiguation

Common names are a real problem. The script uses fuzzy matching (last name + first initial) which is imperfect. To improve accuracy:
- Provide `--arxiv-ids` of known papers to anchor the search
- Restrict to `--categories` the user publishes in
- Provide ORCID when available (future: use ORCID API for precise paper lists)

## Updating Cadence

The profile doesn't need daily updates. Suggested schedule:
- **Monthly** for active researchers
- **On request** ("update my profile")
- **After the user mentions a new paper** (add to known IDs and rebuild)
