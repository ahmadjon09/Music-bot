"""Ephemeral in-memory state: search sessions, callback tokens, download gate.

Telegram callback_data is limited to 64 bytes, so instead of smuggling URLs
through buttons we keep them server-side behind short random tokens.
Everything here is TTL-based — a restarted bot simply forgets, gracefully.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any

from ..downloader import SearchResult

_SEARCH_TTL = 15 * 60   # a search nobody touched for 15 min is history
_TOKEN_TTL = 60 * 60
_MAX_SEARCHES = 200     # LRU cap, so memory stays polite on free tiers


class SearchStore:
    def __init__(self) -> None:
        self._data: OrderedDict[str, tuple[float, str, list[SearchResult]]] = OrderedDict()

    def put(self, query: str, results: list[SearchResult]) -> str:
        self._sweep()
        token = secrets.token_hex(5)
        self._data[token] = (time.time(), query, results)
        while len(self._data) > _MAX_SEARCHES:
            self._data.popitem(last=False)
        return token

    def get(self, token: str) -> tuple[str, list[SearchResult]] | None:
        self._sweep()
        hit = self._data.get(token)
        if not hit:
            return None
        self._data.move_to_end(token)
        _, query, results = hit
        return query, results

    def _sweep(self) -> None:
        now = time.time()
        stale = [k for k, (ts, _, _) in self._data.items() if now - ts > _SEARCH_TTL]
        for key in stale:
            self._data.pop(key, None)


class TokenRegistry:
    """Maps short tokens → arbitrary payloads (URLs, file_ids, …)."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    def put(self, payload: Any) -> str:
        self._sweep()
        token = secrets.token_hex(5)
        self._data[token] = (time.time(), payload)
        return token

    def get(self, token: str) -> Any | None:
        hit = self._data.get(token)
        if not hit or time.time() - hit[0] > _TOKEN_TTL:
            self._data.pop(token, None)
            return None
        return hit[1]

    def _sweep(self) -> None:
        now = time.time()
        for key in [k for k, (ts, _) in self._data.items() if now - ts > _TOKEN_TTL]:
            self._data.pop(key, None)


class DownloadGate:
    """Global + per-user download concurrency, inspired by the original bot."""

    def __init__(self, global_limit: int, user_limit: int) -> None:
        self._global = asyncio.Semaphore(global_limit)
        self._user_limit = user_limit
        self._active: dict[int, int] = {}

    def user_busy(self, user_id: int) -> bool:
        return self._active.get(user_id, 0) >= self._user_limit

    @asynccontextmanager
    async def slot(self, user_id: int):
        self._active[user_id] = self._active.get(user_id, 0) + 1
        try:
            async with self._global:
                yield
        finally:
            left = self._active.get(user_id, 1) - 1
            if left <= 0:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = left


# ── "wow factor" helpers: animated spinners & progress bars ─────────────────
_SPINNERS = ("⏳", "⌛️", "🔄", "⚙️")


def spinner_frame() -> str:
    return _SPINNERS[int(time.time() * 2) % len(_SPINNERS)]


def progress_bar(percent: float, width: int = 12) -> str:
    filled = max(0, min(width, round(width * percent / 100)))
    return "▰" * filled + "▱" * (width - filled)


BOT_STARTED_AT = time.time()


def uptime_text() -> str:
    seconds = int(time.time() - BOT_STARTED_AT)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
