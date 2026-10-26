"""Live runtime settings: proxy pool + cookies, switchable without a restart.

The admin panel (or /setproxy) writes here; every new download picks the
changes up instantly because downloads always ask this object for a fresh
``(cookiefile, proxy)`` pair instead of caching their own.
"""

from __future__ import annotations

import contextlib
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

_K_GLOBAL_COOKIES = "global_cookies"
_K_PROXY_POOL = "proxy_pool"
_K_MAINTENANCE = "maintenance"


@dataclass
class Runtime:
    settings: Settings
    db: Database
    _proxies: list[Proxy] = field(default_factory=list)
    _global_cookies: str | None = None  # decrypted content, memory only
    maintenance: bool = False

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

    # ── proxy pool ───────────────────────────────────────────────────────────
    @property
    def proxies(self) -> list[Proxy]:
        return list(self._proxies)

    def pick_proxy(self) -> str | None:
        """A random proxy URL for this download (spreads load & rate limits)."""
        return random.choice(self._proxies).url if self._proxies else None

    async def set_proxies(self, raw: str) -> list[Proxy]:
        pool = parse_proxy_list(raw)  # raises ProxyParseError on garbage
        self._proxies = pool
        await self.db.kv_set(_K_PROXY_POOL, "\n".join(p.url for p in pool))
        return pool

    async def clear_proxies(self) -> None:
        self._proxies = []
        await self.db.kv_delete(_K_PROXY_POOL)

    def proxy_label(self) -> str:
        if not self._proxies:
            return "direct (no proxy)"
        return ", ".join(p.masked for p in self._proxies)

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
    async def ytdlp_context(self, user_id: int | None) -> AsyncIterator[tuple[str | None, str | None]]:
        """Yield ``(cookiefile_path, proxy_url)``; the cookie file self-destructs.

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
            yield cookiefile, self.pick_proxy()
        finally:
            if cookiefile:
                with contextlib.suppress(OSError):
                    os.remove(cookiefile)
