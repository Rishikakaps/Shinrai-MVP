"""Small transactional SQLite store. Every mutation writes an immutable audit event."""

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
    def __init__(self, root: Path):
        self.root = root
        self.files = root / "files"
        self.files.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.root / "integrity.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, db, cls, entity_id: str, scope: str | None = None):
        row = db.execute("SELECT * FROM objects WHERE id=? AND kind=?", (entity_id, cls.__name__)).fetchone()
        if not row or (scope is not None and row["inspection_id"] != scope):
            raise HTTPException(404, f"{cls.__name__} not found in this inspection")
        return cls.model_validate_json(row["data"])

    def list(self, db, cls, scope: str | None = None):
        sql = "SELECT data FROM objects WHERE kind=?"
        args = [cls.__name__]
        if scope is not None:
            sql += " AND inspection_id=?"
            args.append(scope)
        return [cls.model_validate_json(r[0]) for r in db.execute(sql + " ORDER BY rowid", args)]

    def save(self, db, obj: Entity, actor: str, reason: str, action: str):
        row = db.execute("SELECT data,version FROM objects WHERE id=?", (obj.id,)).fetchone()
        before = json.loads(row["data"]) if row else None
        if row:
            if row["version"] != obj.version:
                raise HTTPException(409, "Stale version; reload and review changes")
            obj.version += 1
            db.execute(
                "UPDATE objects SET version=?, data=? WHERE id=?",
                (obj.version, obj.model_dump_json(), obj.id),
            )
        else:
            db.execute(
                "INSERT INTO objects VALUES (?,?,?,?,?)",
                (obj.id, type(obj).__name__, obj.inspection_id, obj.version, obj.model_dump_json()),
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
        db.execute(
            "INSERT INTO review_events(id,inspection_id,entity_id,data) VALUES (?,?,?,?)",
            (event.id, event.inspection_id, event.entity_id, event.model_dump_json()),
        )
        return obj

    def events(self, db, scope):
        return [
            ReviewEvent.model_validate_json(r[0])
            for r in db.execute(
                "SELECT data FROM review_events WHERE inspection_id=? ORDER BY sequence", (scope,)
            )
        ]
