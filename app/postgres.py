"""Supabase/Postgres adapter preserving the existing typed API and audit semantics."""

import os
from contextlib import contextmanager
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.store import Store

# A single POC write lock preserves multi-entity validation and write ordering.
# Reads use independent repeatable-read snapshots and never take this lock.
WRITE_LOCK = 734105982


class PostgresStore(Store):
    backend = "postgres"
    objects_table = "cdi.objects"
    events_table = "cdi.review_events"
    object_order = "sequence"

    def __init__(self, root: Path, database_url: str, migrate=False):
        self.root = root
        self.files = root / "files"
        self.files.mkdir(parents=True, exist_ok=True, mode=0o700)
        options = conninfo_to_dict(database_url)
        if "supabase" in options.get("host", ""):
            if options.get("sslmode", "require") not in ("require", "verify-ca", "verify-full"):
                raise RuntimeError("Supabase requires an encrypted database connection")
            database_url = make_conninfo(database_url, sslmode=options.get("sslmode", "require"))
        self.pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=int(os.environ.get("CDI_DB_POOL_SIZE", "4")),
            timeout=10,
            kwargs={"row_factory": dict_row, "connect_timeout": 10, "prepare_threshold": None},
            open=True,
        )
        try:
            self.pool.wait(timeout=15)
            if migrate:
                self.migrate()
            self.ready()
        except BaseException:
            self.pool.close()
            raise

    def execute(self, db, sql, args=()):
        return db.execute(sql.replace("?", "%s"), args)

    def json_value(self, value):
        return Jsonb(value)

    @contextmanager
    def transaction(self, write=True):
        with self.pool.connection() as db:
            if write:
                db.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
            else:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield db

    def migrate(self):
        sql = (Path(__file__).parent / "migrations" / "001_postgres.sql").read_text(encoding="utf-8")
        with self.transaction() as db:
            db.execute(sql, prepare=False)

    def close(self):
        self.pool.close()
