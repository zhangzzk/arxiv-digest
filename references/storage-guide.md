# Storage Guide

## Overview

The arxiv-digest skill stores user preferences and profiles in a persistent location under the user's home directory. This ensures data persists across Claude Code sessions and is portable across different setups.

## Storage Location

All skill data is stored in:
```
~/.local/share/arxiv-digest/
├── researcher_profile.json    # Your publication history & network
├── arxiv_preferences.json     # Your reading preferences (learned from feedback)
├── user_record.json           # Auto-updating index of profile + preferences
└── history/                    # Optional: daily digest logs
    ├── 2026-02-10.json
    └── ...
```

**Why this location?**
- Persists across all Claude Code sessions
- Standard location for user-specific data
- Easy to backup, inspect, or reset
- No need to manually upload files each session

Storage root can be overridden for any setup:
1. CLI: `--storage-dir /custom/path/arxiv-digest`
2. Env: `ARXIV_DIGEST_HOME=/custom/path/arxiv-digest`
3. Env: `XDG_DATA_HOME` (uses `$XDG_DATA_HOME/arxiv-digest`)
4. Fallback: `~/.local/share/arxiv-digest`

## Automatic Initialization

The skill automatically:
1. Creates `~/.local/share/arxiv-digest/` on first run if it doesn't exist
2. Detects if profile/preferences are missing
3. Maintains `user_record.json` as an index for both files
4. Prompts you to create missing data

You never need to manually create these directories or files.

## File Schemas

### researcher_profile.json

Built from your arxiv publications. Contains:
- Your papers and publication history
- Co-author collaboration network
- Research topic fingerprint
- Active research categories

See [profile-schema.md](./profile-schema.md) for full spec.

**When to rebuild:**
- First time using the skill
- When you publish new papers (monthly update recommended)
- When you say "update my profile"

### arxiv_preferences.json

Learned from your daily digest feedback. Contains:
- Core research interests (topics you care about)
- Methods you prefer (ML, statistics, simulation, etc.)
- Positive signals (keywords that boost relevance)
- Negative signals (topics to deprioritize)
- Favorite authors to watch for

See [preference-schema.md](./preference-schema.md) for full spec.

**When to update:**
- After each digest when you provide feedback
- Automatically refined over time

## For Skill Developers

### Checking for existing data

```python
import os
import json
from pathlib import Path

STORAGE_DIR = Path.home() / ".claude" / "arxiv-digest"
PROFILE_PATH = STORAGE_DIR / "researcher_profile.json"
PREFS_PATH = STORAGE_DIR / "arxiv_preferences.json"
RECORD_PATH = STORAGE_DIR / "user_record.json"

def ensure_storage_dir():
    """Create storage directory if it doesn't exist."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STORAGE_DIR

def load_profile():
    """Load researcher profile if it exists."""
    if PROFILE_PATH.exists():
        with open(PROFILE_PATH) as f:
            return json.load(f)
    return None

def load_preferences():
    """Load preferences if they exist."""
    if PREFS_PATH.exists():
        with open(PREFS_PATH) as f:
            return json.load(f)
    return None

def save_preferences(prefs):
    """Save updated preferences."""
    ensure_storage_dir()
    with open(PREFS_PATH, 'w') as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)
```

### user_record.json

`user_record.json` is updated whenever profile/preferences are initialized or refreshed. It contains:
- Canonical paths for `researcher_profile.json` and `arxiv_preferences.json`
- Existence, size, and mtime metadata
- Lightweight summaries (name, paper count, category list, etc.)

### Integration with existing scripts

Update the `build_profile.py` script to save directly to `~/.local/share/arxiv-digest/`:

```bash
python3 scripts/build_profile.py \
    --name "Your Name" \
    --storage-dir ~/.local/share/arxiv-digest
```

The fetch script can read preferences from the standard location:

```bash
python3 scripts/arxiv_fetch.py \
    --period today \
    --output /tmp/papers.json
```

## Migration from Old Setup

If you previously stored files in `/mnt/user-data/`, you can migrate:

```bash
# Create new storage location
mkdir -p ~/.local/share/arxiv-digest

# Copy existing files
cp /mnt/user-data/uploads/researcher_profile.json ~/.local/share/arxiv-digest/
cp /mnt/user-data/uploads/arxiv_preferences.json ~/.local/share/arxiv-digest/

# Remove old files (optional)
rm /mnt/user-data/uploads/researcher_profile.json
rm /mnt/user-data/uploads/arxiv_preferences.json
```

## Portability

This storage approach is portable across:
- Different Claude Code installations (same user, same machine)
- Different projects/working directories
- Shell sessions vs VSCode extension

To use on a different machine:
```bash
# On machine A
tar -czf arxiv-digest-backup.tar.gz ~/.local/share/arxiv-digest

# On machine B
tar -xzf arxiv-digest-backup.tar.gz -C ~/
```

## Privacy & Security

- All data is stored locally on your machine
- No data is uploaded to external servers (except when fetching from arxiv API)
- You can inspect/edit files at any time with a text editor
- Delete `~/.local/share/arxiv-digest/` to reset completely

## Troubleshooting

### Files not persisting
- Check that `~/.claude/` directory exists and is writable
- On some systems, ensure `~` expands correctly (use `$HOME` if needed)

### Permission errors
```bash
chmod 755 ~/.local/share/arxiv-digest
chmod 644 ~/.local/share/arxiv-digest/*.json
```

### Starting fresh
```bash
rm -rf ~/.local/share/arxiv-digest
```
The skill will reinitialize on next run.
