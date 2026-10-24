"""Apply versioned POC schema to the DATABASE_URL target; never prints credentials."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.postgres import PostgresStore


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set DATABASE_URL in the private .env before migrating")
    store = PostgresStore(Path(os.environ.get("CDI_DATA_DIR", "data")), url, migrate=True)
    try:
        print("Postgres schema version 1 applied; database readiness passed.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
