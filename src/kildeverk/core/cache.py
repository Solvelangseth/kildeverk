"""An on-disk response cache in one SQLite file.

Entries keep their validators (ETag, Last-Modified) after they expire, so a
stale entry can be revalidated cheaply, or served when upstream is down.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    body BLOB NOT NULL,
    validators TEXT NOT NULL,      -- JSON: etag / last_modified when upstream sent them
    retrieved_at REAL NOT NULL,    -- unix seconds
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS responses_expiry ON responses(expires_at);
"""


@dataclass(frozen=True)
class Entry:
    body: bytes
    validators: dict[str, str]
    retrieved_at: float
    expires_at: float

    def fresh(self, now: float) -> bool:
        return now < self.expires_at


class ResponseCache:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Entry | None:
        async with self._lock:
            row = await asyncio.to_thread(
                lambda: self._db.execute(
                    "SELECT body, validators, retrieved_at, expires_at FROM responses WHERE key = ?",
                    (key,),
                ).fetchone()
            )
        if row is None:
            return None
        return Entry(row[0], json.loads(row[1]), row[2], row[3])

    async def put(
        self,
        key: str,
        *,
        source_id: str,
        body: bytes,
        validators: dict[str, str],
        ttl_s: float,
        retrieved_at: float | None = None,
    ) -> Entry:
        retrieved_at = time.time() if retrieved_at is None else retrieved_at
        entry = Entry(body, validators, retrieved_at, retrieved_at + ttl_s)
        async with self._lock:
            await asyncio.to_thread(
                self._db.execute,
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    source_id,
                    body,
                    json.dumps(validators),
                    entry.retrieved_at,
                    entry.expires_at,
                ),
            )
        return entry

    async def delete(self, key: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._db.execute, "DELETE FROM responses WHERE key = ?", (key,))

    async def stats(self) -> dict[str, dict[str, int]]:
        now = time.time()
        async with self._lock:
            rows = await asyncio.to_thread(
                lambda: self._db.execute(
                    "SELECT source_id, COUNT(*), SUM(expires_at > ?) FROM responses GROUP BY source_id",
                    (now,),
                ).fetchall()
            )
        return {source: {"entries": n, "fresh": int(fresh or 0)} for source, n, fresh in rows}

    def close(self) -> None:
        self._db.close()
