"""Disk-backed TTL cache for Google Places responses.

SQLite file, stdlib only. Key is (function_name, JSON-normalized args).
Different TTLs per function — search results drift faster than place details.

Override the on-disk location with env `PALATE_CACHE_DIR`, or disable entirely
with `PALATE_DISABLE_CACHE=1`. Tests swap in a disabled instance via
`set_default()` so mocked HTTP still fires.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from threading import Lock

# Google Places' TOS permits caching most fields for up to 30 days. We stay
# well under that: restaurant hours and ratings shift in days, not minutes.
DEFAULT_TTLS: dict[str, int] = {
    "search_restaurants": 24 * 3600,        # 1 day
    "get_restaurant_details": 7 * 24 * 3600,  # 7 days
}


class PlacesCache:
    def __init__(
        self,
        path: Path | str,
        ttls: dict[str, int] | None = None,
        disabled: bool = False,
    ):
        self.path = Path(path)
        self.ttls = {**DEFAULT_TTLS, **(ttls or {})}
        self.disabled = disabled
        self._lock = Lock()
        if not self.disabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    fn TEXT NOT NULL,
                    args TEXT NOT NULL,
                    result TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (fn, args)
                )
                """
            )

    @staticmethod
    def _normalize_args(args: dict) -> str:
        # sort_keys so {"a":1,"b":2} and {"b":2,"a":1} share a key.
        return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def get(self, fn: str, args: dict) -> dict | None:
        if self.disabled:
            return None
        key = self._normalize_args(args)
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT result, expires_at FROM cache WHERE fn = ? AND args = ?",
                (fn, key),
            ).fetchone()
            if not row:
                return None
            result_json, expires_at = row
            if expires_at < time.time():
                c.execute("DELETE FROM cache WHERE fn = ? AND args = ?", (fn, key))
                return None
            return json.loads(result_json)

    def put(self, fn: str, args: dict, result: dict) -> None:
        if self.disabled:
            return
        key = self._normalize_args(args)
        ttl = self.ttls.get(fn, 3600)
        expires_at = time.time() + ttl
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache (fn, args, result, expires_at) VALUES (?, ?, ?, ?)",
                (fn, key, json.dumps(result, ensure_ascii=False), expires_at),
            )

    def clear(self) -> int:
        """Wipe all entries. Returns number of rows deleted."""
        if self.disabled:
            return 0
        with self._lock, self._conn() as c:
            n = c.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            c.execute("DELETE FROM cache")
            return n

    def stats(self) -> dict:
        if self.disabled:
            return {"disabled": True}
        with self._lock, self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            expired = c.execute(
                "SELECT COUNT(*) FROM cache WHERE expires_at < ?", (time.time(),)
            ).fetchone()[0]
            by_fn = dict(
                c.execute("SELECT fn, COUNT(*) FROM cache GROUP BY fn").fetchall()
            )
        return {
            "path": str(self.path),
            "total": total,
            "expired": expired,
            "by_fn": by_fn,
        }


_DEFAULT: PlacesCache | None = None


def get_default() -> PlacesCache:
    """Lazy singleton. Env knobs: PALATE_DISABLE_CACHE=1, PALATE_CACHE_DIR=<path>."""
    global _DEFAULT
    if _DEFAULT is None:
        if os.environ.get("PALATE_DISABLE_CACHE") == "1":
            _DEFAULT = PlacesCache(path="/tmp/palate-disabled.sqlite3", disabled=True)
        else:
            base = os.environ.get("PALATE_CACHE_DIR")
            path = (
                Path(base) / "places.sqlite3"
                if base
                else Path.home() / ".cache" / "palate" / "places.sqlite3"
            )
            _DEFAULT = PlacesCache(path=path)
    return _DEFAULT


def set_default(cache: PlacesCache) -> None:
    """For tests and app-level overrides."""
    global _DEFAULT
    _DEFAULT = cache
