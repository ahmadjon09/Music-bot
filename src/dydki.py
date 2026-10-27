"""Search dydki.net's MP3 catalogue and deliver its ready-to-play stream URLs.

The site's result cards expose a ``data-mp3`` URL, artist/title links and a
visible duration.  We parse those server-rendered cards directly instead of
sending text searches to YouTube.  Telegram's own audio cache then keeps the
uploaded ``file_id`` in SQLite so repeat requests are instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp

from .config import Settings
from .downloader import MediaError, SearchResult, TooLargeError
from .httputil import USER_AGENT
from .metadata import clean_title

log = logging.getLogger("musicbot.dydki")

BASE_URL = "https://dydki.net/"
_ALLOWED_MEDIA_HOSTS = {"dydki.net", "www.dydki.net", "mp3vk.sunproxy.net"}
_SEARCH_CACHE_TTL = 10 * 60
_SEARCH_CACHE_SIZE = 64
_MAX_HTML_BYTES = 4 * 1024 * 1024
_DOWNLOAD_CHUNK_SIZE = 128 * 1024


class DydkiError(MediaError):
    """A search/download request to Dydki failed."""

    i18n_key = "error_generic"


def _valid_mp3_url(raw_url: str) -> bool:
    """Accept only HTTPS MP3 streams from Dydki's media host(s)."""
    try:
        parts = urlsplit(raw_url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        return (
            parts.scheme.lower() == "https"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and (host in _ALLOWED_MEDIA_HOSTS or host.endswith(".sunproxy.net"))
            and parts.path.lower().endswith(".mp3")
        )
    except (TypeError, ValueError):
        return False


def _valid_dydki_page_url(raw_url: str) -> bool:
    try:
        parts = urlsplit(raw_url.strip())
        return (parts.scheme.lower() == "https"
                and parts.hostname in {"dydki.net", "www.dydki.net"}
                and parts.username is None and parts.password is None)
    except (TypeError, ValueError):
        return False


def _valid_artwork_url(raw_url: str) -> bool:
    try:
        parts = urlsplit(raw_url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        return (parts.scheme.lower() == "https"
                and parts.username is None and parts.password is None
                and (host in {"dydki.net", "www.dydki.net"}
                     or host.endswith(".sunproxy.net")
                     or host == "dzcdn.net" or host.endswith(".dzcdn.net")))
    except (TypeError, ValueError):
        return False


def _duration_seconds(raw: str) -> int:
    """Parse Dydki's ``m:ss`` / ``h:mm:ss`` display, or return zero."""
    parts = (raw or "").strip().split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return 0
    values = [int(part) for part in parts]
    if len(values) == 2:
        minutes, seconds = values
        if seconds >= 60:
            return 0
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    if minutes >= 60 or seconds >= 60:
        return 0
    return hours * 3600 + minutes * 60 + seconds


class _TrackCardParser(HTMLParser):
    """Small tolerant parser for the ``div.chkd[data-mp3]`` result cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        self._div_depth = 0
        self._capture_field: str | None = None
        self._capture_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        classes = set(values.get("class", "").split())

        if self._card is None:
            if tag == "div" and "chkd" in classes:
                self._card = {"mp3": values.get("data-mp3", "")}
                self._div_depth = 1
            return

        if tag == "div":
            self._div_depth += 1
        elif tag == "a":
            if "track__artist" in classes:
                self._card["artist_url"] = values.get("href", "")
                self._capture_field, self._capture_tag = "artist", "a"
            elif "track__title" in classes:
                self._card["song_url"] = values.get("href", "")
                self._capture_field, self._capture_tag = "title", "a"
        elif tag == "span" and "dur" in classes:
            self._capture_field, self._capture_tag = "duration", "span"
        elif tag == "img" and not self._card.get("thumbnail"):
            self._card["thumbnail"] = values.get("src") or values.get("data-src", "")

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._capture_field:
            self._card[self._capture_field] = self._card.get(self._capture_field, "") + data

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == self._capture_tag:
            self._capture_field, self._capture_tag = None, None
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth <= 0:
                self.cards.append(self._card)
                self._card = None
                self._capture_field, self._capture_tag = None, None

    def close(self) -> None:
        super().close()
        # A truncated HTML response should still yield complete-enough cards.
        if self._card is not None:
            self.cards.append(self._card)
            self._card = None


def parse_search_results(document: str, *, max_results: int = 30,
                         max_duration: int = 600) -> list[SearchResult]:
    """Parse Dydki search HTML into clean, deduplicated song results."""
    parser = _TrackCardParser()
    try:
        parser.feed(document or "")
        parser.close()
    except Exception:  # noqa: BLE001 — malformed site markup must not crash search
        log.debug("could not parse a Dydki result page", exc_info=True)

    results: list[SearchResult] = []
    seen: set[str] = set()
    for card in parser.cards:
        stream_url = urljoin(BASE_URL, card.get("mp3", "").strip())
        if not _valid_mp3_url(stream_url):
            continue

        artist = " ".join(card.get("artist", "").split()).strip()
        title = clean_title(" ".join(card.get("title", "").split()).strip())
        duration = _duration_seconds(card.get("duration", ""))
        if not artist or title == "Unknown title" or duration <= 0 or duration > max_duration:
            continue

        song_url = urljoin(BASE_URL, card.get("song_url", "").strip()) if card.get("song_url") else ""
        artist_url = urljoin(BASE_URL, card.get("artist_url", "").strip()) if card.get("artist_url") else ""
        if not _valid_dydki_page_url(song_url):
            song_url = ""
        if not _valid_dydki_page_url(artist_url):
            artist_url = ""
        # Dydki's song-page ID is stable even if its CDN stream URL rotates.
        song_path = urlsplit(song_url).path if song_url else ""
        numeric_id = re.search(r"-(\d+)/?$", song_path)
        stable_source = song_path if song_path.startswith("/song/") else stream_url
        track_id = numeric_id.group(1) if numeric_id else hashlib.sha256(
            stable_source.encode("utf-8")
        ).hexdigest()[:20]
        if track_id in seen:
            continue
        seen.add(track_id)

        thumbnail = urljoin(BASE_URL, card["thumbnail"]) if card.get("thumbnail") else None
        if thumbnail and not _valid_artwork_url(thumbnail):
            thumbnail = None
        results.append(SearchResult(
            id=track_id,
            title=title,
            uploader=artist,
            duration=duration,
            url=stream_url,
            thumbnail=thumbnail,
            source="dydki",
            page_url=song_url or None,
            artist_url=artist_url or None,
        ))
        if len(results) >= max_results:
            break
    return results


class DydkiClient:
    """Async search/download client with a bounded ten-minute query cache."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._search_cache: OrderedDict[str, tuple[float, list[SearchResult]]] = OrderedDict()

    async def search(self, query: str) -> list[SearchResult]:
        normalized = " ".join((query or "").casefold().split())
        if not normalized:
            return []
        cached = self._search_cache.get(normalized)
        if cached and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL:
            self._search_cache.move_to_end(normalized)
            return list(cached[1])
        if cached:
            self._search_cache.pop(normalized, None)

        try:
            document = await asyncio.wait_for(
                self._request_search_page(query.strip()), timeout=30)
        except TimeoutError as exc:
            raise DydkiError("Dydki search timed out") from exc
        results = parse_search_results(
            document,
            max_results=self.settings.search_results,
            max_duration=self.settings.search_max_duration,
        )
        if results:
            self._search_cache[normalized] = (time.monotonic(), results)
            self._search_cache.move_to_end(normalized)
            while len(self._search_cache) > _SEARCH_CACHE_SIZE:
                self._search_cache.popitem(last=False)
        return list(results)

    async def _request_search_page(self, query: str) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL,
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(BASE_URL, params={"mp3": query}, allow_redirects=True) as response:
                    final_host = (urlsplit(str(response.url)).hostname or "").lower()
                    if final_host not in {"dydki.net", "www.dydki.net"}:
                        raise DydkiError("Dydki redirected outside its catalogue domain")
                    if response.status >= 400:
                        raise DydkiError(f"Dydki returned HTTP {response.status}")
                    raw = await response.content.read(_MAX_HTML_BYTES + 1)
                    if len(raw) > _MAX_HTML_BYTES:
                        raise DydkiError("Dydki search page is too large")
                    charset = response.charset or "utf-8"
                    return raw.decode(charset, errors="replace")
        except asyncio.CancelledError:
            raise
        except DydkiError:
            raise
        except Exception as exc:  # noqa: BLE001 — a direct network/site error
            log.info("Dydki search failed for %r: %s", query, exc)
            raise DydkiError("Could not reach Dydki search") from exc

    async def download_audio(self, url: str, destination: Path) -> Path:
        """Download a Dydki stream only as fallback when Telegram URL import fails."""
        if not _valid_mp3_url(url):
            raise DydkiError("Refusing a non-Dydki MP3 URL")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL,
            "Accept": "audio/mpeg,*/*;q=0.8",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                    if response.status >= 400:
                        raise DydkiError(f"Dydki MP3 returned HTTP {response.status}")
                    if not _valid_mp3_url(str(response.url)):
                        raise DydkiError("Dydki MP3 redirected outside the media hosts")
                    declared_size = response.content_length
                    if declared_size is not None and declared_size > self.settings.max_filesize:
                        raise TooLargeError("Dydki MP3 exceeds the configured size limit")

                    written = 0
                    with destination.open("wb") as output:
                        async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_SIZE):
                            written += len(chunk)
                            if written > self.settings.max_filesize:
                                raise TooLargeError("Dydki MP3 exceeds the configured size limit")
                            output.write(chunk)
                    if written == 0:
                        raise DydkiError("Dydki returned an empty MP3")
                    return destination
        except asyncio.CancelledError:
            destination.unlink(missing_ok=True)
            raise
        except (DydkiError, TooLargeError):
            destination.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001 — direct media network error
            destination.unlink(missing_ok=True)
            log.info("Dydki MP3 fetch failed: %s", exc)
            raise DydkiError("Could not download the Dydki MP3 stream") from exc
