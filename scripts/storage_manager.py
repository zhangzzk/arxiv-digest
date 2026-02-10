#!/usr/bin/env python3
"""
storage_manager.py — Utility for managing arxiv-digest persistent storage

This script helps initialize, inspect, and manage the user's persistent
arxiv-digest data.

Usage:
    python3 storage_manager.py init              # Initialize storage directory
    python3 storage_manager.py status            # Check what files exist
    python3 storage_manager.py paths             # Show storage paths
    python3 storage_manager.py backup [dest]     # Backup all data
    python3 storage_manager.py restore [src]     # Restore from backup
    python3 storage_manager.py reset             # Delete all data (prompts for confirmation)

Dependencies: Python 3.8+ standard library only
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from storage_paths import StoragePaths, get_storage_paths, update_user_record


DATE_FMT = "%Y-%m-%d"


def init_storage(paths: StoragePaths, verbose: bool = True) -> bool:
    """Initialize the storage directory structure."""
    try:
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.history.mkdir(exist_ok=True)
        if not paths.read_state.exists():
            with open(paths.read_state, "w") as f:
                json.dump(_read_state_default(), f, indent=2, ensure_ascii=False)
        update_user_record(paths)

        if verbose:
            print(f"✓ Storage initialized at: {paths.root}")
            print(f"  Profile: {paths.profile}")
            print(f"  Preferences: {paths.prefs}")
            print(f"  Record: {paths.record}")
            print(f"  History: {paths.history}")
            print(f"  Read state: {paths.read_state}")

        return True
    except Exception as e:
        print(f"✗ Failed to initialize storage: {e}", file=sys.stderr)
        return False


def _normalize_date(date_text: str) -> str:
    dt = datetime.strptime(date_text, DATE_FMT)
    return dt.strftime(DATE_FMT)


def _date_range(start_date: str, end_date: str) -> List[str]:
    start_dt = datetime.strptime(_normalize_date(start_date), DATE_FMT).date()
    end_dt = datetime.strptime(_normalize_date(end_date), DATE_FMT).date()
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    dates: List[str] = []
    cursor = start_dt
    while cursor <= end_dt:
        dates.append(cursor.strftime(DATE_FMT))
        cursor += timedelta(days=1)
    return dates


def _read_state_default() -> Dict:
    return {
        "version": 1,
        "last_read_date": "",
        "read_dates": [],
        "updated_at": datetime.now().strftime(DATE_FMT),
    }


def _load_read_state(paths: StoragePaths) -> Dict:
    if not paths.read_state.exists():
        return _read_state_default()
    try:
        with open(paths.read_state) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _read_state_default()
        read_dates = data.get("read_dates", [])
        if not isinstance(read_dates, list):
            read_dates = []
        cleaned = sorted({
            _normalize_date(d) for d in read_dates if isinstance(d, str)
        })
        state = {
            "version": 1,
            "last_read_date": data.get("last_read_date", ""),
            "read_dates": cleaned,
            "updated_at": data.get("updated_at", datetime.now().strftime(DATE_FMT)),
        }
        if state["last_read_date"]:
            state["last_read_date"] = _normalize_date(state["last_read_date"])
        elif cleaned:
            state["last_read_date"] = cleaned[-1]
        return state
    except Exception:
        return _read_state_default()


def _save_read_state(paths: StoragePaths, state: Dict) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().strftime(DATE_FMT)
    with open(paths.read_state, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    update_user_record(paths)


def mark_read_days(paths: StoragePaths, dates: List[str], verbose: bool = True) -> bool:
    try:
        state = _load_read_state(paths)
        merged: Set[str] = set(state.get("read_dates", []))
        merged.update(_normalize_date(d) for d in dates)
        read_dates = sorted(merged)
        state["read_dates"] = read_dates
        state["last_read_date"] = read_dates[-1] if read_dates else ""
        _save_read_state(paths, state)
        if verbose:
            print(f"✓ Marked {len(dates)} day(s) as read")
            print(f"  Last read date: {state['last_read_date'] or 'N/A'}")
            print(f"  Read state: {paths.read_state}")
        return True
    except Exception as e:
        print(f"✗ Failed to mark read days: {e}", file=sys.stderr)
        return False


def mark_unread_days(paths: StoragePaths, dates: List[str], verbose: bool = True) -> bool:
    try:
        state = _load_read_state(paths)
        remove_set = {_normalize_date(d) for d in dates}
        read_dates = [d for d in state.get("read_dates", []) if d not in remove_set]
        state["read_dates"] = read_dates
        state["last_read_date"] = read_dates[-1] if read_dates else ""
        _save_read_state(paths, state)
        if verbose:
            print(f"✓ Marked {len(dates)} day(s) as unread")
            print(f"  Last read date: {state['last_read_date'] or 'N/A'}")
            print(f"  Read state: {paths.read_state}")
        return True
    except Exception as e:
        print(f"✗ Failed to mark unread days: {e}", file=sys.stderr)
        return False


def get_unread_range(
    paths: StoragePaths,
    until: Optional[str] = None,
    default_days: int = 7,
    max_days: int = 30,
) -> Tuple[str, str, int]:
    until_day = _normalize_date(until) if until else datetime.now().strftime(DATE_FMT)
    state = _load_read_state(paths)
    last_read = state.get("last_read_date", "")

    if last_read:
        start_dt = datetime.strptime(last_read, DATE_FMT).date() + timedelta(days=1)
    else:
        window = max(1, min(default_days, max_days))
        start_dt = datetime.strptime(until_day, DATE_FMT).date() - timedelta(days=window - 1)

    until_dt = datetime.strptime(until_day, DATE_FMT).date()
    if start_dt > until_dt:
        return "", "", 0

    span_days = (until_dt - start_dt).days + 1
    if span_days > max_days:
        start_dt = until_dt - timedelta(days=max_days - 1)
        span_days = max_days

    return start_dt.strftime(DATE_FMT), until_day, span_days


def _expand_days_args(date_arg: Optional[str], range_arg: Optional[str]) -> List[str]:
    dates: List[str] = []
    if date_arg:
        dates.append(_normalize_date(date_arg))
    if range_arg:
        parts = range_arg.split(":")
        if len(parts) != 2:
            raise ValueError("range must be START:END in YYYY-MM-DD format")
        dates.extend(_date_range(parts[0].strip(), parts[1].strip()))
    if not dates:
        dates.append(datetime.now().strftime(DATE_FMT))
    return sorted(set(dates))


def check_status(paths: StoragePaths, verbose: bool = True) -> dict:
    """Check the status of stored files."""
    if paths.root.exists():
        update_user_record(paths)

    status = {
        "storage_exists": paths.root.exists(),
        "profile_exists": paths.profile.exists(),
        "prefs_exists": paths.prefs.exists(),
        "record_exists": paths.record.exists(),
        "history_exists": paths.history.exists(),
        "read_state_exists": paths.read_state.exists(),
    }

    if verbose:
        print("Storage Status:")
        print(f"  Storage directory: {'✓' if status['storage_exists'] else '✗'} {paths.root}")
        print(f"  Researcher profile: {'✓' if status['profile_exists'] else '✗'} {paths.profile}")
        print(f"  Preferences: {'✓' if status['prefs_exists'] else '✗'} {paths.prefs}")
        print(f"  User record: {'✓' if status['record_exists'] else '✗'} {paths.record}")
        print(f"  History: {'✓' if status['history_exists'] else '✗'} {paths.history}")
        print(f"  Read state: {'✓' if status['read_state_exists'] else '✗'} {paths.read_state}")

        if status['profile_exists']:
            try:
                with open(paths.profile) as f:
                    profile = json.load(f)
                    name = profile.get('researcher', {}).get('name', 'Unknown')
                    papers = profile.get('publications', {}).get('total_count', 0)
                    built = profile.get('built_at', 'Unknown')
                    print(f"    → Name: {name}")
                    print(f"    → Papers: {papers}")
                    print(f"    → Built: {built}")
            except Exception as e:
                print(f"    → Error reading profile: {e}")

        if status['prefs_exists']:
            try:
                with open(paths.prefs) as f:
                    prefs = json.load(f)
                    interests = len(prefs.get('core_interests', []))
                    categories = len(prefs.get('arxiv_categories', []))
                    updated = prefs.get('last_updated', 'Unknown')
                    print(f"    → Interests: {interests}")
                    print(f"    → Categories: {categories}")
                    print(f"    → Updated: {updated}")
            except Exception as e:
                print(f"    → Error reading preferences: {e}")

        if status['history_exists']:
            history_files = list(paths.history.glob("*.json"))
            print(f"    → History entries: {len(history_files)}")

        if status['read_state_exists']:
            state = _load_read_state(paths)
            print(f"    → Last read date: {state.get('last_read_date') or 'N/A'}")
            print(f"    → Read dates tracked: {len(state.get('read_dates', []))}")

    return status


def show_paths(paths: StoragePaths):
    """Display all storage paths."""
    print("Storage Paths:")
    print(f"  Root: {paths.root}")
    print(f"  Profile: {paths.profile}")
    print(f"  Preferences: {paths.prefs}")
    print(f"  Record: {paths.record}")
    print(f"  History: {paths.history}")
    print(f"  Read state: {paths.read_state}")


def backup_storage(paths: StoragePaths, dest: Optional[str] = None) -> bool:
    """Backup all storage to a tar.gz file."""
    if not paths.root.exists():
        print("✗ No storage directory found. Nothing to backup.", file=sys.stderr)
        return False

    if dest is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = f"arxiv-digest-backup-{timestamp}.tar.gz"

    try:
        # Create a temporary copy to tar
        import tarfile
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(paths.root, arcname="arxiv-digest")

        print(f"✓ Backup created: {dest}")
        print(f"  To restore: python3 storage_manager.py restore {dest}")
        return True
    except Exception as e:
        print(f"✗ Backup failed: {e}", file=sys.stderr)
        return False


def restore_storage(paths: StoragePaths, src: str) -> bool:
    """Restore storage from a backup tar.gz file."""
    src_path = Path(src)
    if not src_path.exists():
        print(f"✗ Backup file not found: {src}", file=sys.stderr)
        return False

    try:
        import tarfile

        # Extract to home directory
        with tarfile.open(src, "r:gz") as tar:
            # Safety check: ensure all paths are within expected roots.
            for member in tar.getmembers():
                if not (
                    member.name.startswith("arxiv-digest")
                    or member.name.startswith(".claude/arxiv-digest")
                ):
                    print(
                        "✗ Invalid backup: contains files outside arxiv-digest roots",
                        file=sys.stderr,
                    )
                    return False

            member_names = [m.name for m in tar.getmembers() if m.name]
            uses_portable_root = any(name.startswith("arxiv-digest") for name in member_names)
            if uses_portable_root:
                paths.root.parent.mkdir(parents=True, exist_ok=True)
                tar.extractall(path=paths.root.parent)
            else:
                # Backward compatibility with old backups that use .claude/arxiv-digest
                tar.extractall(path=Path.home())

        print(f"✓ Restored from: {src}")
        update_user_record(paths)
        check_status(paths)
        return True
    except Exception as e:
        print(f"✗ Restore failed: {e}", file=sys.stderr)
        return False


def reset_storage(paths: StoragePaths, confirm: bool = False) -> bool:
    """Delete all storage data."""
    if not paths.root.exists():
        print("✓ Storage directory already clean (doesn't exist)")
        return True

    if not confirm:
        print(f"This will DELETE all data in: {paths.root}")
        response = input("Are you sure? Type 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Cancelled.")
            return False

    try:
        shutil.rmtree(paths.root)
        print(f"✓ Storage deleted: {paths.root}")
        return True
    except Exception as e:
        print(f"✗ Reset failed: {e}", file=sys.stderr)
        return False


def create_default_preferences(
    paths: StoragePaths,
    categories: list = None,
    interests: list = None,
) -> bool:
    """Create a minimal default preferences file."""
    if paths.prefs.exists():
        print(f"✗ Preferences already exist at: {paths.prefs}", file=sys.stderr)
        return False

    init_storage(paths, verbose=False)

    prefs = {
        "version": 2,
        "core_interests": interests or [],
        "methods_interests": [],
        "positive_signals": [],
        "negative_signals": [],
        "favorite_authors": [],
        "arxiv_categories": categories or ["astro-ph.CO"],
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "history": []
    }

    try:
        with open(paths.prefs, 'w') as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)
        update_user_record(paths)
        print(f"✓ Created default preferences at: {paths.prefs}")
        return True
    except Exception as e:
        print(f"✗ Failed to create preferences: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Manage arxiv-digest persistent storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 storage_manager.py init
  python3 storage_manager.py status
  python3 storage_manager.py backup
  python3 storage_manager.py backup ~/my-backup.tar.gz
  python3 storage_manager.py restore ~/my-backup.tar.gz
  python3 storage_manager.py mark-read --date 2026-02-10
  python3 storage_manager.py unread-range
  python3 storage_manager.py reset
        """,
    )
    parser.add_argument(
        "--storage-dir",
        help="Storage root override (default: ARXIV_DIGEST_HOME, XDG_DATA_HOME/arxiv-digest, or ~/.local/share/arxiv-digest)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Init command
    subparsers.add_parser("init", help="Initialize storage directory")

    # Status command
    subparsers.add_parser("status", help="Check storage status")

    # Paths command
    subparsers.add_parser("paths", help="Show storage paths")

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup all data")
    backup_parser.add_argument("dest", nargs="?", help="Destination file (default: arxiv-digest-backup-TIMESTAMP.tar.gz)")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("src", help="Backup file to restore from")

    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Delete all storage data")
    reset_parser.add_argument("--yes", action="store_true", help="Skip confirmation")

    # Create-prefs command
    create_parser = subparsers.add_parser("create-prefs", help="Create default preferences file")
    create_parser.add_argument("--categories", "-c", nargs="+", help="Arxiv categories")
    create_parser.add_argument("--interests", "-i", nargs="+", help="Research interests")

    # Mark-read command
    mark_read_parser = subparsers.add_parser("mark-read", help="Mark one date or date range as read")
    mark_read_parser.add_argument("--date", help="Single date in YYYY-MM-DD (default: today)")
    mark_read_parser.add_argument("--range", dest="date_range", help="Date range START:END (YYYY-MM-DD:YYYY-MM-DD)")

    # Mark-unread command
    mark_unread_parser = subparsers.add_parser("mark-unread", help="Mark one date or date range as unread")
    mark_unread_parser.add_argument("--date", help="Single date in YYYY-MM-DD (default: today)")
    mark_unread_parser.add_argument("--range", dest="date_range", help="Date range START:END (YYYY-MM-DD:YYYY-MM-DD)")

    # Unread-range command
    unread_parser = subparsers.add_parser(
        "unread-range",
        help="Get period covering the last unread days (from day after last_read_date to --until)",
    )
    unread_parser.add_argument("--until", help="End date in YYYY-MM-DD (default: today)")
    unread_parser.add_argument(
        "--default-days",
        type=int,
        default=7,
        help="Fallback window when no read history exists (default: 7)",
    )
    unread_parser.add_argument(
        "--max-days",
        type=int,
        default=30,
        help="Cap unread span in days (default: 30)",
    )

    args = parser.parse_args()
    paths = get_storage_paths(args.storage_dir)

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    if args.command == "init":
        success = init_storage(paths)
    elif args.command == "status":
        check_status(paths)
        success = True
    elif args.command == "paths":
        show_paths(paths)
        success = True
    elif args.command == "backup":
        success = backup_storage(paths, args.dest)
    elif args.command == "restore":
        success = restore_storage(paths, args.src)
    elif args.command == "reset":
        success = reset_storage(paths, confirm=args.yes)
    elif args.command == "create-prefs":
        success = create_default_preferences(paths, args.categories, args.interests)
    elif args.command == "mark-read":
        try:
            dates = _expand_days_args(args.date, args.date_range)
        except Exception as e:
            print(f"✗ Invalid date input: {e}", file=sys.stderr)
            return 1
        success = mark_read_days(paths, dates)
    elif args.command == "mark-unread":
        try:
            dates = _expand_days_args(args.date, args.date_range)
        except Exception as e:
            print(f"✗ Invalid date input: {e}", file=sys.stderr)
            return 1
        success = mark_unread_days(paths, dates)
    elif args.command == "unread-range":
        try:
            start, end, days = get_unread_range(
                paths,
                until=args.until,
                default_days=max(1, args.default_days),
                max_days=max(1, args.max_days),
            )
            print("Unread Digest Window:")
            if days == 0:
                print("  No unread days in range (already up to date).")
            else:
                print(f"  Start: {start}")
                print(f"  End:   {end}")
                print(f"  Days:  {days}")
                print(f"  Period arg: {start}:{end}")
            success = True
        except Exception as e:
            print(f"✗ Failed to compute unread range: {e}", file=sys.stderr)
            success = False
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
