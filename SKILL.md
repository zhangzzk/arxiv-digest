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

Performance note for `today`:
- if `arxiv_preferences.json` is missing, do not run a failing `--prefs` fetch first; fetch once with explicit `--categories` (or available profile-derived categories).
- prefer `--fast` for interactive "today" digests when low latency matters.
- keep one storage root for all runs (`--storage-dir` or `ARXIV_DIGEST_HOME`) so prefs/profile/output files are not split across `.codex_tmp` and `~/.claude/arxiv-digest`.

Safe-output default:
- `arxiv_fetch.py` now preserves existing `--output` files when a fetch returns 0 papers.
- to intentionally overwrite with an empty array, pass `--allow-empty-output`.

Supported periods include:
- `today`, `week`, `month`, `30d`, `Nd`
- `YYYY-MM-DD`, `YYYY-MM`, `YYYY-MM-DD:YYYY-MM-DD`
- `recent`

For long windows, prefer smaller chunks for reliability:
```bash
python3 scripts/arxiv_fetch.py --period month --chunk-days 5 --output /tmp/papers.json -q
```

If speed is the priority (and occasional misses are acceptable), use fast mode:
```bash
python3 scripts/arxiv_fetch.py --period 10d --chunk-days 5 --fast --output /tmp/papers.json -q
```

Latency guardrail for `today` digests:
- avoid repeated ad-hoc `python -c` probes over the same JSON files.
- do one fetch pass, one ranking pass, and one digest-format pass.
- if key input files are missing, fail fast with one clear message instead of retrying equivalent commands.

Unread-day tracking workflow:
- mark read days after delivering a digest:
```bash
python3 scripts/storage_manager.py mark-read --date 2026-02-10
```
- for "digest of last unread days", compute the unread window first:
```bash
python3 scripts/storage_manager.py unread-range
```
- then fetch that period:
```bash
python3 scripts/arxiv_fetch.py --period YYYY-MM-DD:YYYY-MM-DD --output /tmp/papers.json -q
```

Collection targets by period:
- `today` or single day: 30-80 papers
- `week` (7 days): 80-180 papers
- `month` (30 days): 180-400 papers

If fetch script fails, use manual fallback by scraping `https://arxiv.org/list/{category}/new` or `/recent`.

Fetch integrity checks before ranking:
- record fetch window (`date_from`, `date_to`) and categories used.
- verify `n_total > 0` for multi-category windows unless the user explicitly requested an empty/sparse niche query.
- if any category/chunk failed, report it and mark digest as partial.
- if output already existed and fetch returned 0 papers, do not trust stale assumptions; inspect logs and rerun.

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

Deterministic ranking output:
- build a single ranked list with explicit `score` and `reasons` fields.
- persist ranked data to JSON before writing the human digest.
- never hand-pick Top Picks directly from an unsorted pool.

## Step 4: Present Digest

Use 3 sections in this order:
1. Top Picks
2. Solid Matches
3. Boundary Expanders

### Period-scaled counts

| Period window | Top Picks | Solid Matches | Boundary Expanders | Total shown |
|---|---:|---:|---:|---:|
| `today` / 1 day | 3-8 | 6-12 | 3-5 | 12-25 |
| `week` / ~7 days | 8-14 | 10-16 | 5-8 | 23-38 |
| `month` / ~30 days | 24-36 | 14-24 | 8-12 | 46-72 |
| custom N days | interpolate | interpolate | interpolate | capped |

7-day default:
- 10-12 top picks
- 12-14 solid matches
- 6-8 boundary expanders

Selection policy (required):
- `Top Picks` = first `N_top` items from the ranked list.
- `Solid Matches` = next `N_solid` items from the ranked list.
- `Boundary Expanders` = next `N_boundary` items that have lower direct relevance but clear adjacent value.
- only reorder within a tier for readability if relevance order is preserved.
- if a top-ranked paper is excluded, include an explicit exclusion reason (`duplicate topic`, `superseded`, `outside user scope`, etc.).

Preflight omission check (required):
- compute `top_guard = max(N_top + N_solid, 12)` for daily/weekly windows and scale up for longer windows.
- verify every paper in ranked positions `1..top_guard` appears in `Top Picks` or `Solid Matches`, or has an explicit exclusion reason.
- if this check fails, regenerate the digest instead of replying.

Per paper include:
- unique reference index (global within digest): `#01`, `#02`, ...
- title + arxiv ID
- authors (mark recognized co-authors)
- concise 2-4 sentence summary
- why-it-matches tag
- for boundary papers: `Extends toward: ...`

Title rendering rule (required):
- always print the full original paper title from metadata; do not truncate, abbreviate, or replace with shorthand.
- preserve title punctuation/capitalization as given by source metadata.
- if line length is long, wrap onto the next line instead of shortening the title.

Summary construction rule (required):
- use only information supported by the paper's original abstract metadata (plus explicit ranking signals).
- write exactly 2-4 sentences; do not output one-line blurbs.
- sentence 1: core problem + method/task from the abstract.
- sentence 2: key result, contribution, or dataset/scope from the abstract.
- sentence 3 (optional): caveat, limitation, or context from abstract wording.
- final sentence: explicit `Why it matches` linkage to ranking reasons (topic/method/author/network), not generic praise.
- avoid vague fillers like "interesting work" or "relevant paper" without concrete abstract-grounded details.

Output style:
- numbered list
- prepend each entry with its unique index (e.g., `#07`)
- most relevant first within each section
- concise summaries unless user requests detail

Digest provenance block (required):
- report fetch period, fetch timestamp, categories, total fetched papers, and whether any chunks failed.
- if partial, label the digest as partial at the top.

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
