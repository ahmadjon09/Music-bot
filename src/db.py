"""SQLite storage layer (aiosqlite) — small, fast, zero-ops.

Tables:
  users        — language & quality preferences
  kv           — runtime settings (global cookies (encrypted), proxy pool…)
  user_cookies — per-user encrypted cookies, inherited from the original bot
  file_cache   — Telegram file_id cache: the single biggest speed trick here
  downloads    — delivery log feeding the admin statistics
"""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    lang       TEXT NOT NULL DEFAULT 'uz',
    quality    TEXT NOT NULL DEFAULT '720',
    downloads  INTEGER NOT NULL DEFAULT 0,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_cookies (
    user_id INTEGER PRIMARY KEY,
    data    TEXT NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS file_cache (
    cache_key TEXT PRIMARY KEY,
    file_id   TEXT NOT NULL,
    kind      TEXT NOT NULL,
    title     TEXT,
    performer TEXT,
    duration  INTEGER,
    created   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    url     TEXT,
    kind    TEXT,
    title   TEXT,
    status  TEXT NOT NULL DEFAULT 'ok',
    created REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.execute("PRAGMA journal_mode=WAL")  # readers don't block writers
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database.open() first, hero."
        return self._conn

    # ── users ────────────────────────────────────────────────────────────────
    async def upsert_user(self, user_id: int, detected_lang: str) -> dict:
        now = time.time()
        await self.conn.execute(
            "INSERT INTO users (user_id, lang, first_seen, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen",
            (user_id, detected_lang, now, now),
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else {"user_id": user_id, "lang": detected_lang, "quality": "720"}

    async def set_lang(self, user_id: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
        await self.conn.commit()

    async def set_quality(self, user_id: int, quality: str) -> None:
        await self.conn.execute("UPDATE users SET quality = ? WHERE user_id = ?", (quality, user_id))
        await self.conn.commit()

    async def bump_downloads(self, user_id: int) -> None:
        await self.conn.execute(
            "UPDATE users SET downloads = downloads + 1 WHERE user_id = ?", (user_id,)
        )
        await self.conn.commit()

    # ── key/value runtime settings ───────────────────────────────────────────
    async def kv_get(self, key: str) -> str | None:
        async with self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def kv_set(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    async def kv_delete(self, key: str) -> None:
        await self.conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        await self.conn.commit()

    # ── per-user cookies ─────────────────────────────────────────────────────
    async def get_user_cookies(self, user_id: int) -> str | None:
        async with self.conn.execute(
            "SELECT data FROM user_cookies WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return row["data"] if row else None

    async def set_user_cookies(self, user_id: int, encrypted: str) -> None:
        await self.conn.execute(
            "INSERT INTO user_cookies (user_id, data, updated) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
            (user_id, encrypted, time.time()),
        )
        await self.conn.commit()

    async def delete_user_cookies(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM user_cookies WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ── Telegram file_id cache ───────────────────────────────────────────────
    async def cache_get(self, cache_key: str) -> dict | None:
        async with self.conn.execute(
            "SELECT * FROM file_cache WHERE cache_key = ?", (cache_key,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def cache_put(self, cache_key: str, file_id: str, kind: str,
                        title: str = "", performer: str = "", duration: int = 0) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO file_cache "
            "(cache_key, file_id, kind, title, performer, duration, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cache_key, file_id, kind, title, performer, duration, time.time()),
        )
        await self.conn.commit()

    async def cache_clear(self) -> int:
        cur = await self.conn.execute("DELETE FROM file_cache")
        await self.conn.commit()
        return cur.rowcount

    # ── download log & stats ─────────────────────────────────────────────────
    async def log_download(self, user_id: int, url: str, kind: str,
                           title: str = "", status: str = "ok") -> None:
        await self.conn.execute(
            "INSERT INTO downloads (user_id, url, kind, title, status, created) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, url[:500], kind, title[:300], status, time.time()),
        )
        await self.conn.commit()

    async def stats(self) -> dict:
        out: dict[str, int] = {}
        for name, query in (
            ("users", "SELECT COUNT(*) AS c FROM users"),
            ("downloads", "SELECT COUNT(*) AS c FROM downloads WHERE status = 'ok'"),
            ("cached", "SELECT COUNT(*) AS c FROM file_cache"),
        ):
            async with self.conn.execute(query) as cur:
                row = await cur.fetchone()
            out[name] = int(row["c"]) if row else 0
        return out

    async def recent_downloads(self, limit: int = 15) -> list[dict]:
        async with self.conn.execute(
            "SELECT user_id, kind, title, status, created FROM downloads ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
