"""Transactional typed object store with audited revisions; SQLite local fallback."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.models import Entity, ReviewEvent, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, inspection_id TEXT NOT NULL,
 version INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS objects_scope ON objects(inspection_id, kind);
CREATE TABLE IF NOT EXISTS review_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 inspection_id TEXT NOT NULL, entity_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_scope ON review_events(inspection_id, sequence);
CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON review_events
 BEGIN SELECT RAISE(ABORT, 'Review events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON review_events
 BEGIN SELECT RAISE(ABORT, 'Review events are immutable'); END;
PRAGMA user_version=1;
"""


class Store:
    backend = "sqlite"
    objects_table = "objects"
    events_table = "review_events"
    object_order = "rowid"

    def __init__(self, root: Path):
        self.root = root
        self.files = root / "files"
        self.files.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = self.connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.root / "integrity.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self, write=True):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def execute(self, db, sql, args=()):
        return db.execute(sql, args)

    def json_value(self, value):
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def decode(value):
        return json.loads(value) if isinstance(value, str) else value

    def get(self, db, cls, entity_id, scope=None):
        row = self.execute(
            db, f"SELECT * FROM {self.objects_table} WHERE id=? AND kind=?", (entity_id, cls.__name__)
        ).fetchone()
        if not row or (scope is not None and row["inspection_id"] != scope):
            raise HTTPException(404, f"{cls.__name__} not found in this inspection")
        return cls.model_validate(self.decode(row["data"]))

    def list(self, db, cls, scope=None):
        sql = f"SELECT data FROM {self.objects_table} WHERE kind=?"
        args = [cls.__name__]
        if scope is not None:
            sql += " AND inspection_id=?"
            args.append(scope)
        return [
            cls.model_validate(self.decode(r["data"]))
            for r in self.execute(db, sql + f" ORDER BY {self.object_order}", args)
        ]

    def save(self, db, obj: Entity, actor, reason, action):
        row = self.execute(
            db, f"SELECT data,version FROM {self.objects_table} WHERE id=?", (obj.id,)
        ).fetchone()
        before = self.decode(row["data"]) if row else None
        if row:
            if row["version"] != obj.version:
                raise HTTPException(409, "Stale version; reload and review changes")
            previous = obj.version
            obj.version += 1
            updated = self.execute(
                db,
                f"UPDATE {self.objects_table} SET version=?, data=? WHERE id=? AND version=?",
                (obj.version, self.json_value(obj.model_dump(mode="json")), obj.id, previous),
            )
            if updated.rowcount != 1:
                raise HTTPException(409, "Stale version; reload and review changes")
        else:
            self.execute(
                db,
                f"INSERT INTO {self.objects_table}(id,kind,inspection_id,version,data) VALUES (?,?,?,?,?)",
                (
                    obj.id,
                    type(obj).__name__,
                    obj.inspection_id,
                    obj.version,
                    self.json_value(obj.model_dump(mode="json")),
                ),
            )
        event = ReviewEvent(
            id=str(uuid4()),
            inspection_id=obj.inspection_id,
            entity_id=obj.id,
            action=action,
            author=actor,
            time=now(),
            reason=reason,
            before=before,
            after=obj.model_dump(mode="json"),
        )
        self.execute(
            db,
            f"INSERT INTO {self.events_table}(id,inspection_id,entity_id,data) VALUES (?,?,?,?)",
            (event.id, event.inspection_id, event.entity_id, self.json_value(event.model_dump(mode="json"))),
        )
        return obj

    def events(self, db, scope):
        return [
            ReviewEvent.model_validate(self.decode(r["data"]))
            for r in self.execute(
                db, f"SELECT data FROM {self.events_table} WHERE inspection_id=? ORDER BY sequence", (scope,)
            )
        ]

    def ready(self):
        with self.transaction(write=False) as db:
            self.execute(db, f"SELECT id FROM {self.objects_table} LIMIT 1").fetchone()

    def close(self):
        pass
