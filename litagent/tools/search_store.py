"""Public search-result cache and atomic local request accounting (never answer/LLM memory)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class SearchLimitError(RuntimeError):
    """A search is deferred without making a network request."""


class SearchBudget:
    """One finder request's allowance, shared by its parallel clusters and rewrites."""

    def __init__(self, limit: int):
        if limit < 0:
            raise ValueError("Search budget must be non-negative")
        self.limit, self.used = limit, 0
        self._lock = threading.Lock()

    def consume(self) -> None:
        with self._lock:
            if self.used >= self.limit:
                raise SearchLimitError(f"Coverage search budget used ({self.used}/{self.limit}); external verification deferred")
            self.used += 1


class SearchStore:
    """SQLite transactions keep daily accounting shared across runs and worker processes."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, fetched REAL, capacity INTEGER, complete INTEGER, data TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS quotas (scope TEXT PRIMARY KEY, day TEXT, used INTEGER, blocked_until REAL, reason TEXT)")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, key: str, limit: int, ttl_s: float) -> tuple[dict, float] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT fetched, capacity, complete, data FROM responses WHERE key=?", (key,)).fetchone()
        if row and 0 <= time.time() - row[0] < ttl_s and (row[1] >= limit or row[2]):
            data = json.loads(row[3])
            data["results"] = data.get("results", [])[:limit]
            return data, row[0]
        return None

    def put(self, key: str, limit: int, data: dict) -> None:
        with self._connection() as conn:
            conn.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                         (key, time.time(), limit, len(data.get("results", [])) < limit, json.dumps(data)))

    def reserve(self, scope: str, daily_limit: int, budget: SearchBudget | None = None) -> None:
        stamp = time.time()
        day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT day, used, blocked_until, reason FROM quotas WHERE scope=?", (scope,)).fetchone()
            used = row[1] if row and row[0] == day else 0
            blocked, reason = (row[2], row[3]) if row else (0, "")
            if blocked > stamp:
                raise SearchLimitError(f"{reason} (cached pause; retry in {(blocked - stamp) / 3600:.1f} h)")
            if used >= daily_limit:
                raise SearchLimitError(f"OpenAlex local daily search budget used ({used}/{daily_limit}); retry after midnight UTC")
            if budget is not None:
                budget.consume()
            conn.execute("INSERT OR REPLACE INTO quotas VALUES (?, ?, ?, ?, ?)", (scope, day, used + 1, blocked, reason))

    def block(self, scope: str, wait_s: float, reason: str) -> None:
        stamp = time.time()
        day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT day, used, blocked_until FROM quotas WHERE scope=?", (scope,)).fetchone()
            old_day, used, previous = row if row else (day, 0, 0)
            conn.execute("INSERT OR REPLACE INTO quotas VALUES (?, ?, ?, ?, ?)",
                         (scope, old_day, used, max(previous, stamp + wait_s), reason))
