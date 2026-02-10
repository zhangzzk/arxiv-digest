# Arxiv Digest

Personalized daily Arxiv paper digests with adaptive preference learning.

## Key Features
- **Smart Ranking**: Ranks papers using publication history, co-author networks, and explicit interests.
- **Adaptive Learning**: Refines your preference profile based on daily "like/dislike" feedback.
- **Network Signals**: Highlights papers from your collaborators (👥) and novel "boundary expanders" (🔭).
- **Portable**: Zero-dependency Python scripts for fetching and profile management.

## Components
- `scripts/`: `arxiv_fetch.py` (Arxiv API/scraper) and `build_profile.py` (profile builder).
- `references/`: Schemas for preferences, profiles, and scoring logic.
- `SKILL.md`: Core agent instructions and workflow.

## Quick Start
1. **Initialize**: Use `build_profile.py` to generate your `researcher_profile.json`.
2. **Digest**: The skill fetches daily papers, ranks them, and presents ~10 curated picks.
3. **Refine**: Provide feedback to update your `arxiv_preferences.json` for better future rankings.
