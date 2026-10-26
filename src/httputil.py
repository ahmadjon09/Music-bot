"""aiohttp sessions that speak both HTTP and SOCKS proxies.

aiohttp natively supports http(s) proxies via the ``proxy=`` request
argument, but SOCKS needs ``aiohttp-socks`` and a connector. This helper
hides the split: callers get ``(session, request_proxy)`` and just pass
``proxy=request_proxy`` on every request (None when the connector handles it).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiohttp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def proxy_session(proxy: str | None, *, timeout: int = 30,
                        headers: dict | None = None) -> AsyncIterator[tuple[aiohttp.ClientSession, str | None]]:
    """Yield ``(session, request_proxy)`` for any proxy scheme (or none)."""
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    if proxy and proxy.split("://", 1)[0].lower() in {"socks4", "socks5", "socks5h"}:
        from aiohttp_socks import ProxyConnector

        connector = ProxyConnector.from_url(proxy, ssl=False)
        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout,
                                         headers=merged) as session:
            yield session, None
        return

    async with aiohttp.ClientSession(timeout=client_timeout, headers=merged) as session:
        yield session, proxy
