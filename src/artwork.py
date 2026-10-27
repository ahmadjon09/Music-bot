"""Best-effort artist portraits for Dydki search results.

Dydki's ``.chkd`` song cards contain artist/title/duration and the MP3 stream,
but generally no artwork.  This optional Deezer lookup supplies an artist
portrait for Telegram's audio thumbnail; failures are harmless and cached
briefly so search/delivery never depends on the artwork service.
"""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from collections import OrderedDict
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from .httputil import proxy_session
from .metadata import prepare_cover

log = logging.getLogger("musicbot.artwork")
_DEEZER_SEARCH_URL = "https://api.deezer.com/search/artist"
_CACHE_TTL = 24 * 60 * 60
_NEGATIVE_CACHE_TTL = 15 * 60
_CACHE_SIZE = 128
_MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _normalise_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", (value or "").casefold())
    return "".join(char for char in value if char.isalnum())


def _artist_image_url(artist: str, payload: object) -> str | None:
    """Pick the closest Deezer artist match with a usable portrait URL."""
    if not isinstance(payload, dict):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list):
        return None
    target = _normalise_name(artist)
    if not target:
        return None

    candidates: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        candidate = _normalise_name(name)
        if not candidate:
            continue
        if candidate == target:
            score = 1.0
        elif len(target) < 4:
            continue  # short names need an exact hit; fuzzy matches are too risky
        elif target in candidate or candidate in target:
            score = min(len(target), len(candidate)) / max(len(target), len(candidate))
        else:
            score = SequenceMatcher(None, target, candidate).ratio()
        image = str(row.get("picture_xl") or row.get("picture_big") or row.get("picture_medium") or "")
        parts = urlsplit(image)
        host = (parts.hostname or "").lower()
        if (parts.scheme == "https" and parts.username is None and parts.password is None
                and (host == "dzcdn.net" or host.endswith(".dzcdn.net"))):
            candidates.append((score, image))
    if not candidates:
        return None
    score, image = max(candidates, key=lambda item: item[0])
    # Avoid attaching a portrait for an unrelated artist returned by fuzzy search.
    return image if score >= 0.68 else None


def _proxy_attempts(proxy: str | list[str] | None) -> list[str | None]:
    if isinstance(proxy, str):
        candidates: list[str | None] = [proxy] if proxy else []
    else:
        candidates = list(proxy or [])
    if None not in candidates:
        candidates.append(None)
    return candidates or [None]


class ArtistArtworkClient:
    """Fetches compact JPEG portraits and keeps a small in-memory cache."""

    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[float, bytes | None]] = OrderedDict()

    async def get_image(self, artist: str, *, proxy: str | list[str] | None = None) -> bytes | None:
        key = _normalise_name(artist)
        if not key:
            return None
        cached = self._cache.get(key)
        if cached:
            created, image = cached
            ttl = _CACHE_TTL if image else _NEGATIVE_CACHE_TTL
            if time.monotonic() - created < ttl:
                self._cache.move_to_end(key)
                return image
            self._cache.pop(key, None)

        image = await self._load_image(artist.strip(), proxy=proxy)
        self._cache[key] = (time.monotonic(), image)
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return image

    async def _load_image(self, artist: str, *, proxy: str | list[str] | None) -> bytes | None:
        headers = {"Accept": "application/json,image/*;q=0.8"}
        for candidate in _proxy_attempts(proxy):
            try:
                async with proxy_session(candidate, timeout=12, headers=headers) as (session, req_proxy):
                    async with session.get(_DEEZER_SEARCH_URL, params={"q": artist},
                                           proxy=req_proxy) as response:
                        if response.status != 200:
                            continue
                        payload = await response.json(content_type=None)
                        image_url = _artist_image_url(artist, payload)
                        if not image_url:
                            continue
                        image = await self._download_image(image_url, proxy=candidate)
                        if image:
                            return image
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — art is decoration, not a song dependency
                log.debug("artist image lookup failed for %r", artist, exc_info=True)
        return None

    async def _download_image(self, url: str, *, proxy: str | None) -> bytes | None:
        try:
            async with proxy_session(proxy, timeout=12, headers={"Accept": "image/*"}) as (session, req_proxy):
                async with session.get(url, proxy=req_proxy, allow_redirects=True) as response:
                    if response.status != 200:
                        return None
                    host = (urlsplit(str(response.url)).hostname or "").lower()
                    if host != "dzcdn.net" and not host.endswith(".dzcdn.net"):
                        return None
                    if response.content_length and response.content_length > _MAX_IMAGE_BYTES:
                        return None
                    raw = await response.content.read(_MAX_IMAGE_BYTES + 1)
                    if len(raw) > _MAX_IMAGE_BYTES:
                        return None
            return await asyncio.to_thread(prepare_cover, raw, square=True, max_size=320)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — image failures are non-fatal
            log.debug("artist portrait download failed", exc_info=True)
            return None
