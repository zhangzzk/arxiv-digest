---
name: arxiv-digest
description: >
  Personalized daily arxiv paper digest with preference learning. Use this skill whenever
  the user asks about new arxiv papers, wants a daily paper digest, asks "what's new on arxiv",
  wants paper recommendations, or mentions reading/browsing arxiv. Also trigger when the user
  says things like "papers today", "new preprints", "arxiv update", or "what should I read".
  This skill fetches, ranks, and presents papers tailored to the user's research interests,
  and iteratively learns their preferences over time.
---

# Arxiv Daily Digest

A skill for fetching new arxiv listings, ranking them by user interest, and learning preferences over time.

## Overview

This skill:
1. Fetches today's new arxiv submissions from relevant categories
2. Ranks papers by relevance to the user's research profile
3. Presents ~10 top papers in two tiers: core matches + boundary expanders
4. Asks the user for feedback to refine their preference profile
5. Persists the preference profile for future sessions

## Step 1: Load User Profile and Preferences

The skill uses two complementary data sources:
- **Researcher profile** (`researcher_profile.json`) — who the user is, their papers, co-authors, and research network. Built automatically from arxiv metadata.
- **Reading preferences** (`arxiv_preferences.json`) — what the user wants to read. Learned from explicit feedback.

### Check for existing files

Look in `/mnt/user-data/uploads/` for:
1. `researcher_profile.json` — the user's research profile
2. `arxiv_preferences.json` — their reading preferences

### If no profile exists: build one

Ask the user for their basic info and build their profile:

```
What's your name as it appears on your papers? (e.g., "Jane M. Doe")
Optionally: affiliation, ORCID, or a few arxiv IDs of your papers.
```

Then run the profile builder:
```bash
python3 scripts/build_profile.py \
    --name "Jane M. Doe" \
    --affiliation "University of Somewhere" \
    --categories astro-ph.CO astro-ph.IM \
    --output /tmp/researcher_profile.json
```

If the user provides specific arxiv IDs, add `--arxiv-ids 2301.00001 2205.12345`.

The script automatically:
- Finds the user's papers via the arxiv API
- Extracts all co-authors and builds a collaboration network
- Identifies the user's research topics from their publication titles/abstracts
- Determines their active arxiv categories

Save the profile to `/mnt/user-data/outputs/researcher_profile.json`.

### If no preferences exist

If there's a profile but no preferences, bootstrap preferences from the profile:
- Use `research_fingerprint.topic_keywords` as `core_interests` and `positive_signals`
- Use `publications.primary_categories` as `arxiv_categories`
- Use `network.active_coauthors` as `favorite_authors`
- Leave `negative_signals` empty (learned from feedback)

If neither file exists AND the user doesn't provide their name, ask for their interests as keywords and create a basic preference file (skip the profile for now).

### Updating the profile

The profile doesn't need daily updates. Refresh it when:
- The user says "update my profile"
- Monthly, if the user is active
- The user mentions a new paper they published

```bash
python3 scripts/build_profile.py --update researcher_profile.json --output researcher_profile.json
```

The preference profile has this structure — see `references/preference-schema.md` for details:

```json
{
  "version": 2,
  "core_interests": ["cosmology", "galaxy surveys", "weak lensing"],
  "methods_interests": ["simulation-based inference", "Bayesian statistics", "ML"],
  "positive_signals": ["intrinsic alignments", "photometric redshifts"],
  "negative_signals": ["warm inflation", "holographic dark matter"],
  "favorite_authors": [],
  "arxiv_categories": ["astro-ph.CO", "astro-ph.GA", "astro-ph.IM", "stat.ML"],
  "last_updated": "2025-11-14"
}
```

## Step 2: Fetch Papers

Use the bundled scraper script to fetch papers efficiently:

```bash
python3 scripts/arxiv_fetch.py --prefs /path/to/arxiv_preferences.json --period today --output /tmp/papers.json -q
```

The script handles everything: API calls, RSS feeds, HTML fallback, deduplication, and filtering. It outputs clean JSON with just the fields you need.

### Script usage

| Period | Command | Notes |
|--------|---------|-------|
| Today's new | `--period today` | Uses RSS feed (primary) or HTML scrape (fallback) |
| Past week | `--period week` | Uses API submittedDate query |
| Specific date | `--period 2025-11-14` | Uses API |
| Date range | `--period 2025-11-10:2025-11-14` | Uses API |
| Recent | `--period recent` | HTML scrape of /list/{cat}/recent |

You can also specify categories directly instead of using a prefs file:
```bash
python3 scripts/arxiv_fetch.py -c astro-ph.CO astro-ph.GA astro-ph.IM -t today -o /tmp/papers.json -q
```

The script is zero-dependency (Python 3.8+ stdlib only) and respects arxiv's rate limits (3s between API requests).

### Fallback: manual web_fetch

If the script fails (e.g., network restrictions), fall back to using `web_fetch` on `https://arxiv.org/list/{category}/new` directly. Parse the HTML to extract arxiv IDs, titles, authors, and abstracts. Use `text_content_token_limit` of 8000-12000 per fetch and deduplicate across categories.

### Output format

The script outputs a JSON array of paper objects:
```json
[
  {
    "arxiv_id": "2511.10616",
    "title": "A new multiprobe analysis of modified gravity...",
    "authors": ["Zhiyu Lu", "Théo Simon", "Yi-Fu Cai"],
    "abstract": "We study the (w0, wa) parametrization...",
    "categories": ["astro-ph.CO", "hep-ph"],
    "primary_category": "astro-ph.CO",
    "published": "2025-11-13T18:00:00Z",
    "updated": "2025-11-13T18:00:00Z",
    "comment": "14+10 pages, 12 figures, 3 tables",
    "journal_ref": "",
    "doi": "",
    "announce_type": "new"
  }
]
```

Target: collect 30-80 papers across all categories.

## Step 3: Score and Rank Papers

For each paper, compute a relevance score using BOTH the preference profile AND the researcher profile. The combination of keyword matching (preferences) and network signals (profile) produces much better rankings than either alone.

### Preference-based signals

**High relevance signals** (each adds significant weight):
- Title/abstract keywords match `core_interests`
- Methods in abstract match `methods_interests`
- Paper matches `positive_signals`
- Authors in `favorite_authors`
- Cross-listed between two of the user's categories (e.g., astro-ph.CO + stat.ML)

**Moderate relevance signals:**
- Paper is in one of user's categories but topic is adjacent
- Novel method applied to a familiar domain
- Major survey data (DESI, Euclid, Rubin, DES, Planck) mentioned

**Low relevance / negative signals:**
- Topic matches `negative_signals` — deprioritize but don't hide
- Purely theoretical with no data/inference component (if user is methods-focused)
- Very narrow niche outside user's field

### Network-based signals (from researcher profile)

When a researcher profile is available, add these scoring boosts:

| Signal | Boost | How to detect |
|--------|-------|---------------|
| **Active co-author** | Very strong | Author in `network.active_coauthors` |
| **Any co-author** | Strong | Author in `network.coauthor_rank` |
| **2nd-degree contact** | Mild | Author in `network.second_degree_rank` |
| **Research fingerprint overlap** | Moderate | Paper keywords overlap with `research_fingerprint.topic_keywords` |
| **Cites user's work** | Strong | Paper abstract/refs mention the user's paper IDs (rare but detectable in some cases) |

Network signals are *additive* with preference signals. A paper that matches preferences AND is by a co-author should rank very high. A paper by a co-author that doesn't match preferences should still surface (co-authors often work on things the user cares about).

### Special: co-author papers

Papers by active co-authors deserve special treatment:
- Always include in the digest even if the topic seems off-interest
- Flag them with a 👥 marker so the user knows why they're included
- If a co-author paper is also a topic match, it goes to the very top

### Boundary expander scoring

A paper qualifies as a "boundary expander" if it:
- Is in a related but not core category
- Uses a method the user likes on a new domain
- Introduces a new technique relevant to the user's problems
- Is by a 2nd-degree network contact (someone your collaborators work with)
- Is a high-impact paper (Nature/Science/PRL) in an adjacent field

## Step 4: Present the Digest

Present papers in two sections:

### Top Picks (5-8 papers)
These are the closest matches to the user's core interests. For each paper:
- **Title** with arxiv ID link
- **Authors** (first 3 + "et al." if more). Mark co-authors with 👥 if recognized from the network
- **One-paragraph summary** focused on what's novel and why it matters to this user
- **Tag line** showing which interests it hits (e.g., "→ Hits: galaxy survey, SBI, systematics")
- If a co-author paper: add "👥 Co-author: [name]" to the tag line

### Boundary Expanders (3-5 papers)
Papers that stretch the user's interests in potentially valuable directions:
- Same format as above
- Add a **"Extends toward:"** line explaining what new territory this represents
- If by a 2nd-degree network contact, note: "🔗 Via your network: [co-author name] collaborates with [author]"

### Formatting rules:
- Use numbered list with bold titles
- Keep summaries concise (2-4 sentences)
- Put the most relevant paper first within each section
- Include the arxiv ID so the user can click through
- Use emoji sparingly: 🎯 for top picks header, 🔭 for boundary expanders header

## Step 5: Collect Feedback

After presenting, ask the user which papers they're interested in and which they're not. Use the `ask_user_input` tool with multi-select options when available.

Good questions to ask:
1. "Which papers caught your eye?" (multi-select from the list)
2. "Any topics you want me to filter out next time?" (multi-select of topic categories)
3. "Any authors or groups you want me to watch for?" (open-ended, optional)

## Step 6: Update Preferences

Based on feedback, update the preference profile:

- Papers the user liked → extract keywords, add to `positive_signals`
- Papers the user disliked → extract topics, add to `negative_signals`
- Explicitly mentioned authors → add to `favorite_authors`
- If a "boundary expander" was liked → consider promoting its topic to `core_interests`

Save the updated profile to `/mnt/user-data/outputs/arxiv_preferences.json`.

Tell the user the file is saved and they can re-upload it next time for continuity, or (if memory is enabled) note that preferences have been updated.

## Edge Cases

- **Weekend/holiday**: Arxiv doesn't post on weekends. If "new" is empty or stale, try fetching from `/list/{category}/pastweek` or `/list/{category}/recent` instead.
- **Too many papers**: If >100 papers, be more aggressive in filtering. Only present the top tier.
- **Too few papers**: If <10 papers across all categories, broaden to related categories or fetch from `/recent` instead of `/new`.
- **Network issues**: If fetches fail, inform the user and suggest trying again later. Don't fabricate paper listings.
- **User has no preference file and doesn't provide interests**: Ask them! Don't guess.

## Additional References

- `references/preference-schema.md` — Full preference file schema and migration notes
- `references/profile-schema.md` — Researcher profile schema, network scoring guide, and build instructions
- `references/scoring-guide.md` — Detailed scoring rubric with examples
