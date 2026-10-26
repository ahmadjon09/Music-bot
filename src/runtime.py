"""Live runtime settings: proxy pool + cookies, switchable without a restart.

The admin panel (or /setproxy) writes here; every new download picks the
changes up instantly because downloads always ask this object for a fresh
``(cookiefile, proxy)`` pair instead of caching their own.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from . import security
from .config import Settings
from .db import Database
from .proxy import Proxy, parse_proxy_list
from .proxypool import ProxyPool

log = logging.getLogger("musicbot.runtime")

_K_GLOBAL_COOKIES = "global_cookies"
_K_PROXY_POOL = "proxy_pool"
_K_PROXY_MODE = "proxy_mode"
_K_POOL_CACHE = "proxy_pool_cache"
_K_MAINTENANCE = "maintenance"


@dataclass
class Runtime:
    settings: Settings
    db: Database
    _proxies: list[Proxy] = field(default_factory=list)
    _global_cookies: str | None = None  # decrypted content, memory only
    maintenance: bool = False
    pool: ProxyPool | None = None  # self-maintaining free-proxy pool
    proxy_mode: str = "auto"  # "manual" pins admin proxies; "auto" uses the pool

    async def load(self) -> None:
        """Hydrate from the DB; fall back to env-provided defaults."""
        raw_pool = await self.db.kv_get(_K_PROXY_POOL)
        if not raw_pool and self.settings.initial_proxy:
            raw_pool = self.settings.initial_proxy
        if raw_pool:
            with contextlib.suppress(Exception):
                self._proxies = parse_proxy_list(raw_pool)

        blob = await self.db.kv_get(_K_GLOBAL_COOKIES)
        if blob:
            self._global_cookies = security.decrypt_text(self.settings.secret_key, blob)

        self.maintenance = (await self.db.kv_get(_K_MAINTENANCE)) == "1"

        # Free-proxy pool: restore the last verified set so the very first
        # download after a restart already has exits to rotate through.
        pool = self._ensure_pool()
        cached = await self.db.kv_get(_K_POOL_CACHE) or ""
        with contextlib.suppress(ValueError, TypeError):
            urls = json.loads(cached)
            if isinstance(urls, list) and urls:
                pool.set_healthy([str(u) for u in urls])
        stored_mode = await self.db.kv_get(_K_PROXY_MODE)
        self.proxy_mode = stored_mode or ("manual" if self._proxies else "auto")

    def _ensure_pool(self) -> ProxyPool:
        if self.pool is None:
            self.pool = ProxyPool(target_size=self.settings.proxy_pool_size)
        return self.pool

    # ── proxy pool ───────────────────────────────────────────────────────────
    @property
    def proxies(self) -> list[Proxy]:
        return list(self._proxies)

    def proxy_candidates(self, limit: int = 3) -> list[str]:
        """Ordered proxy URLs for one operation — rotation happens caller-side.

        Manual mode pins the admin-provided proxies (WARP, paid, …); auto
        mode uses the self-maintaining free pool and falls back to manual
        entries while the pool is still warming up.
        """
        manual = [p.url for p in self._proxies]
        random.shuffle(manual)
        if self.proxy_mode == "manual" and manual:
            return manual[:limit]
        pooled = self._ensure_pool().candidates(limit)
        return pooled or manual[:limit]

    def pick_proxy(self) -> str | None:
        candidates = self.proxy_candidates(1)
        return candidates[0] if candidates else None

    async def set_proxy_mode(self, mode: str) -> None:
        self.proxy_mode = "manual" if mode == "manual" else "auto"
        await self.db.kv_set(_K_PROXY_MODE, self.proxy_mode)

    def report_proxy_failure(self, url: str | None) -> None:
        if url and self.pool:
            self.pool.report_failure(url)

    def report_proxy_success(self, url: str | None) -> None:
        if url and self.pool:
            self.pool.report_success(url)

    async def _persist_pool(self) -> None:
        if self.pool:
            urls = self.pool.healthy_urls()
            if urls:
                await self.db.kv_set(_K_POOL_CACHE, json.dumps(urls))

    async def refresh_pool_now(self) -> dict:
        """Admin-triggered rescan; also persists the fresh verified set."""
        stats = await self._ensure_pool().refresh()
        await self._persist_pool()
        return stats

    async def run_proxy_worker(self) -> None:
        """Background loop keeping the free-proxy pool fresh (cancellable)."""
        if not self.settings.auto_proxy:
            return
        pool = self._ensure_pool()
        while True:
            try:
                await pool.refresh()
                await self._persist_pool()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — the worker must outlive surprises
                log.exception("proxy pool refresh failed")
            await asyncio.sleep(self.settings.proxy_refresh_minutes * 60)

    def pool_stats(self) -> dict:
        stats = self.pool.stats() if self.pool else {
            "healthy": 0, "last_refresh": 0.0, "last_scanned": 0,
            "refreshing": False, "top": [],
        }
        return {
            "mode": self.proxy_mode,
            "auto_enabled": self.settings.auto_proxy,
            "refresh_minutes": self.settings.proxy_refresh_minutes,
            "manual": len(self._proxies),
            **stats,
        }

    async def set_proxies(self, raw: str) -> list[Proxy]:
        pool = parse_proxy_list(raw)  # raises ProxyParseError on garbage
        self._proxies = pool
        await self.db.kv_set(_K_PROXY_POOL, "\n".join(p.url for p in pool))
        await self.set_proxy_mode("manual")  # explicit proxies = explicit intent
        return pool

    async def clear_proxies(self) -> None:
        self._proxies = []
        await self.db.kv_delete(_K_PROXY_POOL)
        await self.set_proxy_mode("auto")  # back to the self-maintaining pool

    def proxy_label(self) -> str:
        if self._proxies:
            return ", ".join(p.masked for p in self._proxies)
        if self.pool and self.pool.healthy_urls():
            return f"auto pool ({len(self.pool.healthy_urls())} YouTube-verified)"
        return "direct (no proxy)"

    # ── cookies ──────────────────────────────────────────────────────────────
    @property
    def has_global_cookies(self) -> bool:
        return bool(self._global_cookies)

    def global_cookies_report(self) -> dict:
        if not self._global_cookies:
            return {"ok": False, "total": 0, "domains": {}}
        return security.validate_cookies(self._global_cookies)

    async def set_global_cookies(self, content: str) -> None:
        self._global_cookies = content
        blob = security.encrypt_text(self.settings.secret_key, content)
        await self.db.kv_set(_K_GLOBAL_COOKIES, blob)

    async def clear_global_cookies(self) -> None:
        self._global_cookies = None
        await self.db.kv_delete(_K_GLOBAL_COOKIES)

    async def cookies_for_user(self, user_id: int | None) -> str | None:
        """Personal cookies win over the admin's global jar."""
        if user_id is not None:
            blob = await self.db.get_user_cookies(user_id)
            if blob:
                plain = security.decrypt_text(self.settings.secret_key, blob)
                if plain:
                    return plain
        return self._global_cookies

    async def set_maintenance(self, on: bool) -> None:
        self.maintenance = on
        await self.db.kv_set(_K_MAINTENANCE, "1" if on else "0")

    # ── the one-stop shop used by every download ─────────────────────────────
    @asynccontextmanager
    async def ytdlp_context(self, user_id: int | None) -> AsyncIterator[tuple[str | None, list[str]]]:
        """Yield ``(cookiefile_path, [proxy_url, …])``; the cookie file self-destructs.

        Cookies are materialised to a private temp file (yt-dlp insists on a
        real path) with 0600 permissions and deleted the moment we're done.
        """
        content = await self.cookies_for_user(user_id)
        cookiefile: str | None = None
        try:
            if content:
                fd, cookiefile = tempfile.mkstemp(
                    dir=self.settings.tmp_dir, prefix="cookies_", suffix=".txt"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.chmod(cookiefile, 0o600)
            yield cookiefile, self.proxy_candidates(3)
        finally:
            if cookiefile:
                with contextlib.suppress(OSError):
                    os.remove(cookiefile)
