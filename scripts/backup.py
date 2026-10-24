"""Verified SQLite backup. Supabase/Postgres needs database-native backup plus originals."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from app.models import Evidence
from app.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if os.environ.get("DATABASE_URL", "").strip():
        raise SystemExit("Postgres selected: use a Postgres backup and coordinated originals snapshot.")
    source = Path(os.environ.get("CDI_DATA_DIR", "data")).resolve()
    target = args.destination.resolve()
    if not (source / "integrity.sqlite3").is_file() or not (source / "files").is_dir():
        raise SystemExit("Source database/files do not exist; refusing to create an empty backup")
    if target == source or source in target.parents or target.exists():
        raise SystemExit("Choose a new backup directory outside the data directory")
    store = Store(source)
    with store.transaction() as lock:
        originals = store.list(lock, Evidence)
        for ev in originals:
            file = store.files / ev.sha256
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != ev.sha256:
                raise SystemExit("Original missing or corrupt; backup refused")
        target.mkdir(parents=True, mode=0o700)
        reader = store.connect()
        destination = sqlite3.connect(target / "integrity.sqlite3")
        try:
            reader.backup(destination)
            shutil.copytree(store.files, target / "files")
            for ev in originals:
                if hashlib.sha256((target / "files" / ev.sha256).read_bytes()).hexdigest() != ev.sha256:
                    raise RuntimeError("Copied original failed verification")
            (target / "backup-manifest.json").write_text(
                json.dumps(
                    {"database": "sqlite", "originals_verified": len(originals), "complete": True}, indent=2
                ),
                encoding="utf-8",
            )
        finally:
            reader.close()
            destination.close()
    print("Consistent database and evidence backup created; original digests verified.")


if __name__ == "__main__":
    main()
