# Scoring Guide for Paper Ranking

## Goal

Rank papers the way a knowledgeable colleague would: high personal relevance first, then useful adjacent work.

## Tiers

### Tier 1: Top Picks

Use when paper matches:
- `2+` core interests, or
- `1` core interest + `1` methods interest,
- and has clear substance.

### Tier 2: Solid Matches

Use when paper is relevant but weaker than Tier 1:
- partial topic overlap,
- important survey/result update,
- useful method with limited direct fit.

### Tier 3: Boundary Expanders

Use when paper can broaden capability:
- method transfer from adjacent domain,
- new technique relevant to user problems,
- network-adjacent but not core-topic fit.

### Tier 4: Skip Unless Curious

Use when mostly off-interest and low expected value.

## Period-Scaled Presentation Targets

| Period window | Tier 1 (Top Picks) | Tier 2 (Solid Matches) | Tier 3 (Boundary Expanders) | Total shown |
|---|---:|---:|---:|---:|
| 1 day (`today`) | 1-5 | 4-8 | 2-3 | 7-16 |
| 7 days (`week`) | 5-10 | 5-10 | 3-6 | 13-26 |
| 30 days (`month`) | 18-30 | 8-15 | 5-10 | 31-55 |

For custom windows, interpolate and round to practical integers.

## Scoring Signals

### Title/Abstract

Boost for:
- user core topics and methods
- explicit survey names and major data products
- concrete result language ("constraint", "measurement", "inference")

Reduce for:
- clearly off-focus niche areas
- theory-only papers when user is methods/data focused

### Authors/Network

Boost levels:
- very strong: active co-author
- strong: known co-author
- mild: second-degree network contact

Always explain network-based boosts in output.

### Categories

Cross-listing can be highly informative:
- domain + methods categories often indicates strong fit
- domain + very theoretical category may indicate weaker fit

## Decision Rules

1. Topic relevance comes first.
2. Network boosts are additive, not a replacement for relevance.
3. Co-author papers should still surface, even if not Tier 1.
4. Keep section ordering strict: Top Picks -> Solid Matches -> Boundary Expanders.
5. Assign each surfaced paper a unique digest index (`#01`, `#02`, ...) for user feedback.
6. Keep output bounded by period caps.
7. If user requests a deep dive on a surfaced paper, switch from ranking mode to full-paper mode (load and use the full PDF content).
8. Update `researcher_profile.json` continuously when user provides durable profile facts (new papers/collaborators/affiliation/ORCID), not just on periodic refresh.

## Anti-Patterns

- Ranking by hype/news instead of user relevance.
- Overweighting one keyword.
- Ignoring cross-lists and methods overlap.
- Returning unbounded long lists.
- Copying abstracts instead of summarizing.
