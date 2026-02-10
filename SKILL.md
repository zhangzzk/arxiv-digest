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

Fetch, rank, and present arxiv papers using two persistent user files:
- `researcher_profile.json` (research identity + network)
- `arxiv_preferences.json` (reading interests + feedback history)

## Workflow

1. Load or bootstrap profile/preferences.
2. Fetch papers for requested period.
3. Rank papers with preference + network signals.
4. Present period-scaled digest in 3 tiers.
5. Collect feedback and profile updates from interaction.

## Step 1: Profile and Preferences

### Storage

Use this storage root resolution order:
1. `--storage-dir /path/to/arxiv-digest`
2. `ARXIV_DIGEST_HOME`
3. `XDG_DATA_HOME/arxiv-digest`
4. `~/.claude/arxiv-digest` (fallback)

Expected files:
- `researcher_profile.json`
- `arxiv_preferences.json`
- `user_record.json` (auto-updating file index/summary)

### If profile is missing

Ask:
```
What's your name as it appears on your papers? Optionally affiliation, ORCID, or a few arxiv IDs.
```

Build:
```bash
python3 scripts/build_profile.py \
  --name "Jane M. Doe" \
  --affiliation "University of Somewhere" \
  --categories astro-ph.CO astro-ph.IM
```

Refresh existing profile when user asks, monthly, or after new publications:
```bash
python3 scripts/build_profile.py \
  --update ~/.claude/arxiv-digest/researcher_profile.json \
  --output ~/.claude/arxiv-digest/researcher_profile.json
```

### If preferences are missing

Bootstrap from profile:
- `core_interests` from `research_fingerprint.topic_keywords`
- `arxiv_categories` from `publications.primary_categories`
- `favorite_authors` from `network.active_coauthors`
- start `negative_signals` empty

If no profile and no name available, ask for interest keywords and create a basic preferences file.

## Step 2: Fetch Papers

Primary command:
```bash
python3 scripts/arxiv_fetch.py --period today --output /tmp/papers.json -q
```

Supported periods include:
- `today`, `week`, `month`, `30d`, `Nd`
- `YYYY-MM-DD`, `YYYY-MM`, `YYYY-MM-DD:YYYY-MM-DD`
- `recent`

For long windows, prefer smaller chunks for reliability:
```bash
python3 scripts/arxiv_fetch.py --period month --chunk-days 5 --output /tmp/papers.json -q
```

Collection targets by period:
- `today` or single day: 30-80 papers
- `week` (7 days): 80-180 papers
- `month` (30 days): 180-400 papers

If fetch script fails, use manual fallback by scraping `https://arxiv.org/list/{category}/new` or `/recent`.

## Step 3: Score and Rank

Combine preference and network signals.

Preference signals:
- strong: `core_interests`, `methods_interests`, `positive_signals`, favorite authors
- medium: adjacent topic, major survey relevance
- negative: `negative_signals`, clearly off-focus niche

Network boosts from profile:
- very strong: `network.active_coauthors`
- strong: `network.coauthor_rank`
- mild: `network.second_degree_rank`
- moderate: overlap with `research_fingerprint.topic_keywords`

Co-author policy:
- always surface active co-author papers
- annotate them clearly

## Step 4: Present Digest

Use 3 sections in this order:
1. Top Picks
2. Solid Matches
3. Boundary Expanders

### Period-scaled counts

| Period window | Top Picks | Solid Matches | Boundary Expanders | Total shown |
|---|---:|---:|---:|---:|
| `today` / 1 day | 1-5 | 4-8 | 2-3 | 7-16 |
| `week` / ~7 days | 5-10 | 5-10 | 3-6 | 13-26 |
| `month` / ~30 days | 18-30 | 8-15 | 5-10 | 31-55 |
| custom N days | interpolate | interpolate | interpolate | capped |

7-day default:
- 5-10 top picks
- 5-10 solid matches
- 3-6 boundary expanders

Per paper include:
- unique reference index (global within digest): `#01`, `#02`, ...
- title + arxiv ID
- authors (mark recognized co-authors)
- concise 2-4 sentence summary
- why-it-matches tag
- for boundary papers: `Extends toward: ...`

Output style:
- numbered list
- prepend each entry with its unique index (e.g., `#07`)
- most relevant first within each section
- concise summaries unless user requests detail

## Step 5: Collect Feedback

Ask:
1. Which paper IDs were useful? (e.g., `#03`, `#11`)
2. Which topics should be filtered next time?
3. Which authors/groups should be watched?
4. Any profile changes? (new paper IDs, new collaborators, affiliation/ORCID updates)

## Step 6: Deep Dive on Selected Papers

If the user asks to dive into a paper (by digest index like `#03` or by arxiv ID):
1. Resolve digest index -> `arxiv_id`.
2. Load the full paper, not just abstract metadata.
3. Use full-paper content as the basis for detailed explanation and Q&A.

Recommended source order:
1. arxiv PDF: `https://arxiv.org/pdf/{arxiv_id}.pdf`
2. arxiv abs page for metadata cross-check: `https://arxiv.org/abs/{arxiv_id}`

Deep-dive response should include:
- problem setup and assumptions
- method/algorithm details
- key equations or model components (in words unless user asks for derivation)
- experiment/data setup
- main results and limitations
- practical takeaways and follow-up reading pointers

When uncertain, quote section names/figure numbers from the full paper and clearly distinguish paper claims from assistant interpretation.

## Step 7: Dynamically Update Profile

During each interaction, update `researcher_profile.json` when the user provides durable profile facts:
- new publication arxiv IDs
- new/recent collaborators
- affiliation, homepage, ORCID, or preferred name updates
- explicit request: "update my profile"

Update policy:
1. Lightweight update immediately after interaction:
   - patch known fields in profile JSON directly
   - append newly provided paper IDs if missing
2. Full refresh when needed:
   - run `build_profile.py --update ...` when user reports new publications,
     collaborator network likely changed, or profile is stale.

Refresh command:
```bash
python3 scripts/build_profile.py \
  --update ~/.claude/arxiv-digest/researcher_profile.json \
  --output ~/.claude/arxiv-digest/researcher_profile.json
```

Save updated profile:
- `~/.claude/arxiv-digest/researcher_profile.json` (or resolved storage root)

## Step 8: Update Preferences

Apply feedback:
- liked papers -> add keywords to `positive_signals`
- disliked papers -> add to `negative_signals`
- mentioned authors -> add to `favorite_authors`
- liked expanders -> promote topic toward `core_interests` when appropriate

Save updated preferences:
- `~/.claude/arxiv-digest/arxiv_preferences.json` (or resolved storage root)

## Edge Cases

- Weekend/holiday: if `/new` is empty, use `/pastweek` or `/recent`.
- Too many papers: enforce period caps; do not dump unbounded lists.
- Too few papers: broaden categories or use `recent`.
- Network/API failures: report failure; do not fabricate listings.
- Missing interest data: ask user directly instead of guessing.

## References

- `references/scoring-guide.md`
- `references/storage-guide.md`
- `references/preference-schema.md`
- `references/profile-schema.md`
