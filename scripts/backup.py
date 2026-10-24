"""Consistent backup under the same SQLite writer lock as API mutations. Keeps originals and audit."""

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

from app.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = Path(os.environ.get("CDI_DATA_DIR", "data")).resolve()
    target = args.destination.resolve()
    if target == source or source in target.parents or target.exists():
        raise SystemExit("Choose a new backup directory outside the data directory")
    store = Store(source)
    target.mkdir(parents=True, mode=0o700)
    with store.transaction():
        # A separate reader can copy the committed snapshot while this connection holds the writer lock.
        reader = store.connect()
        destination = sqlite3.connect(target / "integrity.sqlite3")
        try:
            reader.backup(destination)
            shutil.copytree(store.files, target / "files")
        finally:
            reader.close()
            destination.close()
    print("Consistent database and evidence backup created.")


if __name__ == "__main__":
    main()
