"""Opaque, revocable browser sessions. Existing API bearer authentication stays supported."""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException

SESSION_SECONDS = 12 * 60 * 60
COOKIE = "cdi_session"


class BrowserSessions:
    def __init__(self, store, tokens):
        self.store = store
        self.table = "cdi.browser_sessions" if store.backend == "postgres" else "browser_sessions"
        self.tokens = tokens
        self.credentials = {hashlib.sha256(t.encode()).hexdigest(): p for t, p in tokens.items()}
        with store.transaction() as db:
            store.execute(
                db,
                f"""CREATE TABLE IF NOT EXISTS {self.table} (
                sid_hash TEXT PRIMARY KEY, credential_hash TEXT NOT NULL,
                csrf TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)""",
            )

    @staticmethod
    def secure(request):
        return os.environ.get("CDI_COOKIE_SECURE", "").lower() == "true" or request.url.scheme == "https"

    def issue(self, token):
        principal = None
        for key, value in self.tokens.items():
            if hmac.compare_digest(key.encode(), token.encode()):
                principal = value
        if principal is None:
            return None
        sid, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        with self.store.transaction() as db:
            self.store.execute(db, f"DELETE FROM {self.table} WHERE expires<?", (time.time(),))
            self.store.execute(
                db,
                f"INSERT INTO {self.table} VALUES(?,?,?,?)",
                (
                    hashlib.sha256(sid.encode()).hexdigest(),
                    hashlib.sha256(token.encode()).hexdigest(),
                    csrf,
                    time.time() + SESSION_SECONDS,
                ),
            )
        return sid

    def read(self, request):
        sid = request.cookies.get(COOKIE, "")
        if not sid:
            return None
        with self.store.transaction(write=False) as db:
            row = self.store.execute(
                db,
                f"SELECT * FROM {self.table} WHERE sid_hash=? AND expires>?",
                (hashlib.sha256(sid.encode()).hexdigest(), time.time()),
            ).fetchone()
        if not row or row["credential_hash"] not in self.credentials:
            return None
        return {**self.credentials[row["credential_hash"]], "csrf": row["csrf"]}

    def validate_write(self, request, session):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied.encode(), session["csrf"].encode()):
            raise HTTPException(403, "Refresh this page before saving (CSRF check failed)")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin browser writes are not permitted")

    def revoke(self, request):
        sid = request.cookies.get(COOKIE, "")
        with self.store.transaction() as db:
            self.store.execute(
                db, f"DELETE FROM {self.table} WHERE sid_hash=?", (hashlib.sha256(sid.encode()).hexdigest(),)
            )
