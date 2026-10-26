"""Self-maintaining free-proxy pool for YouTube.

Free proxy lists (TheSpeedX/PROXY-List) refresh every few minutes, but most
entries are dead on arrival. This worker:

  1. takes the lists from the top (freshest first), plus a small bootstrap
     seed of proxies previously measured against YouTube,
  2. probes candidates concurrently against YouTube's ``generate_204``
     endpoint until enough healthy ones are found,
  3. keeps them ranked by latency and re-scans on a timer,

so the downloader always has fresh, YouTube-capable exit IPs to rotate
through — no human babysitting, no stale "best proxy" graveyards.

Public proxies are untrusted middleboxes: the bot only ever sends them
public download traffic (HTTPS), never user data or bot tokens.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import aiohttp

from .httputil import proxy_session
from .proxy import ProxyParseError, parse_proxy

log = logging.getLogger("musicbot.proxypool")

#: Source lists, in priority order (scheme is implied by the file name).
DEFAULT_SOURCES: tuple[tuple[str, str], ...] = (
    ("http", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("socks5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    ("socks4", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
)

_YOUTUBE_PROBE = "https://www.youtube.com/generate_204"

#: Bootstrap seeds — measured against YouTube (204, ranked by latency) from
#: the operator's own scan of the list above. They rot like all free
#: proxies; the worker verifies every one before first use anyway.
SEED_PROXIES: tuple[str, ...] = (
    "http://47.254.36.25:11080", "http://162.214.159.94:3128",
    "http://34.43.46.91:80", "http://18.221.175.172:8000",
    "http://34.105.252.3:3128", "http://104.194.146.9:80",
    "http://51.15.20.32:3129", "http://103.237.102.191:11111",
    "http://4.144.146.21:80", "http://176.111.37.216:39811",
    "http://176.111.37.5:39811", "http://45.125.64.215:443",
    "http://112.216.54.226:12121", "http://89.167.124.218:8888",
    "http://184.75.221.82:3118", "http://206.223.241.13:3128",
    "http://34.43.46.91:443", "http://102.244.78.61:8082",
    "http://85.90.207.232:3128", "http://185.196.182.22:8080",
)


@dataclass
class ScoredProxy:
    url: str
    latency_ms: float
    fails: int = 0
    last_fail: float = 0.0


@dataclass
class ProxyPool:
    """Ranked, self-refreshing pool of YouTube-verified public proxies."""

    target_size: int = 12
    scan_limit: int = 800
    concurrency: int = 40
    probe_timeout: float = 6.0
    seeds: tuple[str, ...] = SEED_PROXIES
    sources: tuple[tuple[str, str], ...] = DEFAULT_SOURCES

    _healthy: list[ScoredProxy] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_refresh: float = 0.0
    last_scanned: int = 0
    refreshing: bool = False

    # ── picking ──────────────────────────────────────────────────────────────
    def candidates(self, limit: int = 3) -> list[str]:
        """Up to ``limit`` proxy URLs, best first, failures cooled down."""
        now = time.time()
        alive = [p for p in self._healthy if p.fails < 3 or now - p.last_fail > 300]
        alive.sort(key=lambda p: p.latency_ms)
        top = alive[: max(limit, 5)]
        random.shuffle(top)  # spread load across the fastest handful
        return [p.url for p in top[:limit]]

    def report_failure(self, url: str) -> None:
        for proxy in self._healthy:
            if proxy.url == url:
                proxy.fails += 1
                proxy.last_fail = time.time()

    def report_success(self, url: str) -> None:
        for proxy in self._healthy:
            if proxy.url == url:
                proxy.fails = 0

    def healthy_urls(self) -> list[str]:
        """Healthy proxy URLs, fastest first (for persistence/inspection)."""
        return [p.url for p in sorted(self._healthy, key=lambda p: p.latency_ms)]

    def set_healthy(self, urls: list[str]) -> None:
        """Install a pre-ranked list (boot-time restore / tests)."""
        self._healthy = [ScoredProxy(url=u, latency_ms=100.0 + i) for i, u in enumerate(urls)]

    def stats(self) -> dict:
        return {
            "healthy": len(self._healthy),
            "last_refresh": self.last_refresh,
            "last_scanned": self.last_scanned,
            "refreshing": self.refreshing,
            "top": [{"proxy": p.url.split("@")[-1], "ms": round(p.latency_ms)}
                    for p in sorted(self._healthy, key=lambda p: p.latency_ms)[:5]],
        }

    # ── refreshing ───────────────────────────────────────────────────────────
    async def _fetch_candidates(self) -> list[str]:
        """Seeds first, then each source list top-to-bottom, de-duplicated."""
        ordered: list[str] = list(self.seeds)
        seen = set(ordered)
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for scheme, source in self.sources:
                try:
                    async with session.get(source) as resp:
                        if resp.status != 200:
                            continue
                        text = await resp.text()
                except Exception:  # noqa: BLE001 — one dead source is not fatal
                    log.debug("proxy source unreachable: %s", source)
                    continue
                for line in text.splitlines():
                    raw = line.strip()
                    if not raw or raw.startswith("#"):
                        continue
                    candidate = raw if "://" in raw else f"{scheme}://{raw}"
                    try:
                        url = parse_proxy(candidate).url
                    except ProxyParseError:
                        continue
                    if url not in seen:
                        seen.add(url)
                        ordered.append(url)
        return ordered

    async def _test_one(self, url: str) -> float | None:
        """Latency in ms if YouTube answers through this proxy, else None."""
        started = time.monotonic()
        try:
            async with proxy_session(url, timeout=int(self.probe_timeout) + 2) as (session, req_proxy):
                async with session.get(_YOUTUBE_PROBE, proxy=req_proxy,
                                       timeout=aiohttp.ClientTimeout(total=self.probe_timeout)) as resp:
                    if resp.status in (200, 204):
                        return (time.monotonic() - started) * 1000
        except Exception:  # noqa: BLE001 — dead proxy, move on quietly
            return None
        return None

    async def refresh(self) -> dict:
        """Scan from the top of the lists until the pool is full of life."""
        if self._lock.locked():
            return self.stats()
        async with self._lock:
            self.refreshing = True
            try:
                candidates = await self._fetch_candidates()
                healthy: list[ScoredProxy] = []
                sem = asyncio.Semaphore(self.concurrency)
                scanned = 0
                index = 0
                # Work down the list in waves; stop as soon as we have enough.
                while index < len(candidates) and scanned < self.scan_limit \
                        and len(healthy) < self.target_size:
                    wave = candidates[index:index + self.concurrency * 2]
                    index += len(wave)
                    scanned += len(wave)

                    async def _probe(url: str) -> ScoredProxy | None:
                        async with sem:
                            latency = await self._test_one(url)
                        return ScoredProxy(url=url, latency_ms=latency) if latency is not None else None

                    results = await asyncio.gather(*(_probe(u) for u in wave))
                    healthy.extend(r for r in results if r is not None)
                healthy.sort(key=lambda p: p.latency_ms)
                # Only replace the live pool when the scan found *something*;
                # a total network outage shouldn't nuke a working pool.
                if healthy:
                    previous = {p.url: p for p in self._healthy}
                    for proxy in healthy:
                        if old := previous.get(proxy.url):
                            proxy.fails = old.fails
                    self._healthy = healthy[: self.target_size * 2]
                self.last_refresh = time.time()
                self.last_scanned = scanned
                log.info("proxy pool refreshed: %d healthy of %d scanned",
                         len(self._healthy), scanned)
                return self.stats()
            finally:
                self.refreshing = False

    async def run_forever(self, interval_minutes: int = 15) -> None:
        """Background worker: refresh now, then on a timer. Cancellable."""
        try:
            await self.refresh()
            while True:
                await asyncio.sleep(max(60, interval_minutes * 60))
                await self.refresh()
        except asyncio.CancelledError:
            log.debug("proxy pool worker stopped")
            raise
