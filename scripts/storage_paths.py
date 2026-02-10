#!/usr/bin/env python3
"""
storage_paths.py — Shared storage path and record helpers for arxiv-digest.

Supports portable storage resolution:
1) --storage-dir argument (passed in by caller)
2) ARXIV_DIGEST_HOME environment variable
3) XDG_DATA_HOME/arxiv-digest
4) ~/.claude/arxiv-digest (default fallback)
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class StoragePaths:
    root: Path
    profile: Path
    prefs: Path
    record: Path
    history: Path
    read_state: Path


def get_storage_paths(storage_dir: Optional[str] = None) -> StoragePaths:
    root = _resolve_storage_root(storage_dir)
    return StoragePaths(
        root=root,
        profile=root / "researcher_profile.json",
        prefs=root / "arxiv_preferences.json",
        record=root / "user_record.json",
        history=root / "history",
        read_state=root / "read_state.json",
    )


def ensure_storage_dirs(paths: StoragePaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.history.mkdir(parents=True, exist_ok=True)


def update_user_record(
    paths: StoragePaths,
    profile_path: Optional[Path] = None,
    prefs_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write/update user_record.json with pointers and lightweight summaries."""
    ensure_storage_dirs(paths)

    profile = (profile_path or paths.profile).expanduser()
    prefs = (prefs_path or paths.prefs).expanduser()

    existing = _read_json(paths.record) if paths.record.exists() else {}
    created_at = existing.get("created_at", _now_iso())

    record: Dict[str, Any] = {
        "version": 1,
        "created_at": created_at,
        "updated_at": _now_iso(),
        "storage_root": str(paths.root),
        "files": {
            "researcher_profile": _build_profile_entry(profile),
            "arxiv_preferences": _build_prefs_entry(prefs),
            "read_state": _build_read_state_entry(paths.read_state),
        },
    }

    with open(paths.record, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    return record


def _resolve_storage_root(storage_dir: Optional[str] = None) -> Path:
    if storage_dir:
        return Path(storage_dir).expanduser().resolve()

    env_root = os.environ.get("ARXIV_DIGEST_HOME")
    if env_root:
        return Path(env_root).expanduser().resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "arxiv-digest").resolve()

    return (Path.home() / ".claude" / "arxiv-digest").resolve()


def _build_profile_entry(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = _file_info(path)
    if not path.exists():
        return info

    data = _read_json(path)
    if data:
        info["summary"] = {
            "name": data.get("researcher", {}).get("name", ""),
            "publication_count": data.get("publications", {}).get("total_count", 0),
            "primary_categories": data.get("publications", {}).get("primary_categories", []),
            "built_at": data.get("built_at", ""),
        }
    return info


def _build_prefs_entry(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = _file_info(path)
    if not path.exists():
        return info

    data = _read_json(path)
    if data:
        info["summary"] = {
            "core_interests_count": len(data.get("core_interests", [])),
            "methods_interests_count": len(data.get("methods_interests", [])),
            "favorite_authors_count": len(data.get("favorite_authors", [])),
            "arxiv_categories": data.get("arxiv_categories", []),
            "last_updated": data.get("last_updated", ""),
        }
    return info


def _build_read_state_entry(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = _file_info(path)
    if not path.exists():
        return info

    data = _read_json(path)
    if data:
        read_dates = data.get("read_dates", [])
        info["summary"] = {
            "last_read_date": data.get("last_read_date", ""),
            "read_dates_count": len(read_dates) if isinstance(read_dates, list) else 0,
            "updated_at": data.get("updated_at", ""),
        }
    return info


def _file_info(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if path.exists():
        stat = path.stat()
        info["size_bytes"] = stat.st_size
        info["modified_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    return info


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _now_iso() -> str:
    return datetime.now().isoformat()
