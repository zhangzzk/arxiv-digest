# Arxiv Digest

A personal arxiv reading assistant that learns what you care about.

It does three things well:
- finds new papers for your time window (`today`, `week`, `month`, custom ranges)
- ranks them using your interests and collaborator network
- gets better over time from your feedback

## Quick start

```bash
python3 scripts/storage_manager.py init
python3 scripts/build_profile.py --name "Your Name" --categories astro-ph.CO stat.ML
python3 scripts/storage_manager.py status
```

## Daily flow

1. Ask for a digest (for example: "what's new this week?").
2. Review ranked papers with stable IDs like `#01`, `#02`.
3. Give feedback on what was useful.
4. Ask for a deep dive on any paper ID; `arxiv-digest` will route to relevant companion skills:
   - `pdf` for full-paper reading and evidence checks
   - `jupyter-notebook` for experiments/reproduction
   - `doc` for polished `.docx` notes/writeups
   - `notion-knowledge-capture` for structured Notion capture

## Unread-day flow

Track what you've already read:
```bash
python3 scripts/storage_manager.py mark-read --date 2026-02-10
```

Get "last unread days" window:
```bash
python3 scripts/storage_manager.py unread-range
```

Use returned period with fetch:
```bash
python3 scripts/arxiv_fetch.py --period YYYY-MM-DD:YYYY-MM-DD --output /tmp/papers.json -q
```

## Where your data lives

`~/.claude/arxiv-digest/`
- `researcher_profile.json`
- `arxiv_preferences.json`
- `user_record.json`
- `history/`

You can override storage with `--storage-dir`, `ARXIV_DIGEST_HOME`, or `XDG_DATA_HOME`.

## Files

- `SKILL.md`: workflow and behavior
- `scripts/`: fetch/profile/storage utilities
- `references/`: scoring and schema details
