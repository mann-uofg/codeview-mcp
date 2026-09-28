"""Tiny SQLite cache for AI responses, so re-reviewing the same diff doesn't burn free-tier quota."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path

from platformdirs import user_cache_dir

log = logging.getLogger(__name__)

DEFAULT_TTL = 7 * 24 * 3600


def cache_dir() -> Path:
    override = os.environ.get("CODEVIEW_CACHE_DIR")
    return Path(override) if override else Path(user_cache_dir("codeview", appauthor=False))


def make_key(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()


class ResponseCache:
    def __init__(self, path: Path | None = None, ttl: int = DEFAULT_TTL) -> None:
        self.path = path or cache_dir() / "responses.sqlite3"
        self.ttl = ttl

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, created INTEGER, body TEXT)")
        return con

    def get(self, key: str) -> str | None:
        try:
            with contextlib.closing(self._connect()) as con:
                row = con.execute("SELECT created, body FROM responses WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            log.debug("cache read failed: %s", exc)
            return None
        if not row or time.time() - row[0] > self.ttl:
            return None
        return str(row[1])

    def put(self, key: str, body: str) -> None:
        try:
            with contextlib.closing(self._connect()) as con:
                con.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?)", (key, int(time.time()), body))
                con.execute("DELETE FROM responses WHERE created < ?", (int(time.time()) - self.ttl,))
        except sqlite3.Error as exc:
            log.debug("cache write failed: %s", exc)

    def clear(self) -> int:
        try:
            with contextlib.closing(self._connect()) as con:
                return con.execute("DELETE FROM responses").rowcount
        except sqlite3.Error:
            return 0
