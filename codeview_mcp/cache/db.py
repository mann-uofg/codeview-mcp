"""
Tiny SQLite cache wrapper
✓ WAL journal - reduces writer contention
✓ 5-second busy timeout
✓ Connections closed after each call
"""

from __future__ import annotations
import sqlite3, json, pathlib, time, contextlib
from typing import Any

# ---------------------------------------------------------------------------
DB_PATH = pathlib.Path(".cache") / "reviewgenie.db"
DB_PATH.parent.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    """
    Return a new connection with:
      • 5-second timeout while DB is busy
      • WAL journal mode for better concurrency
      • autocommit (isolation_level=None)
    """
    con = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS pr_cache ("
        "  key TEXT PRIMARY KEY,"
        "  fetched_at INTEGER,"
        "  data TEXT)"
    )
    return con

# ---------------------------------------------------------------------------
def get(key: str, max_age_hours: int = 24) -> Any | None:
    """
    Return cached object or None if:
      • key absent
      • entry older than *max_age_hours*
    """
    with contextlib.closing(_connect()) as con:
        row = con.execute(
            "SELECT fetched_at, data FROM pr_cache WHERE key = ?",
            (key,),
        ).fetchone()

    if not row:
        return None

    age_hrs = (time.time() - row[0]) / 3600
    return json.loads(row[1]) if age_hrs <= max_age_hours else None

# ---------------------------------------------------------------------------
def put(key: str, data: Any) -> None:
    """
    Insert or update cache entry.
    """
    blob = json.dumps(data)
    with contextlib.closing(_connect()) as con:
        con.execute(
            "INSERT OR REPLACE INTO pr_cache(key, fetched_at, data)"
            " VALUES(?,?,?)",
            (key, int(time.time()), blob),
        )
