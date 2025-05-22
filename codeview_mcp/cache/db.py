import sqlite3, json, pathlib, time
from typing import Any

DB_PATH = pathlib.Path(".cache") / "reviewgenie.db"
DB_PATH.parent.mkdir(exist_ok=True)

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pr_cache ("
        "  key TEXT PRIMARY KEY, "          # e.g. 'psf/requests#6883'
        "  fetched_at INTEGER, "            # epoch seconds
        "  data TEXT                        " # JSON blob
        ")"
    )
    return conn

def get(key: str, max_age_hours: int = 24) -> Any | None:
    row = _conn().execute(
        "SELECT fetched_at, data FROM pr_cache WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    age = (time.time() - row[0]) / 3600
    return json.loads(row[1]) if age <= max_age_hours else None

def put(key: str, data: Any) -> None:
    blob = json.dumps(data)
    _conn().execute(
        "INSERT OR REPLACE INTO pr_cache(key, fetched_at, data) VALUES(?,?,?)",
        (key, int(time.time()), blob),
    )
    _conn().commit()
