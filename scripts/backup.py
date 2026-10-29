"""Create a consistent SQLite + private media backup.

Usage:
    python scripts/backup.py [--destination backups/trainly-2026-10-29]

Stop the app and worker only if you need a strict point-in-time copy; SQLite's
backup API still produces a consistent database copy while they are running.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("TRAINLY_DB", ROOT / "trainly.sqlite3"))
STORAGE = Path(os.environ.get("TRAINLY_STORAGE", ROOT / "storage"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up Trainly's SQLite database and private media")
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "backups" / time.strftime("trainly-%Y%m%d-%H%M%S"),
    )
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"Backup destination already exists and is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    if not DB.is_file():
        raise SystemExit(f"Database not found: {DB}")
    target_db = destination / DB.name
    source = sqlite3.connect(DB)
    target = sqlite3.connect(target_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    media_target = destination / "storage"
    if STORAGE.is_dir():
        shutil.copytree(STORAGE, media_target, dirs_exist_ok=True)
    manifest = {
        "created_at": int(time.time()),
        "database": DB.name,
        "storage": "storage",
        "files": sorted(path.name for path in media_target.glob("*") if path.is_file()) if media_target.is_dir() else [],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Backup written to {destination}")


if __name__ == "__main__":
    main()
