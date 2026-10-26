"""The download engine — an async-friendly façade over yt-dlp.

Speed tricks used here:
  * blocking yt-dlp work runs in worker threads (``asyncio.to_thread``),
    so the bot stays responsive for everyone else;
  * audio prefers a native M4A/MP3 stream — no re-encode in the hot path;
  * multi-fragment downloads (``concurrent_fragment_downloads``);
  * progress hooks bridge back into the event loop, throttled, so the UI
    animates without hammering Telegram's edit API;
  * every job gets its own temp directory that is always cleaned up —
    no zombie files, no zombie processes, no surprises at 3 a.m.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

from .config import Settings, resolve_ffmpeg, resolve_js_runtime
from .httputil import proxy_session
from .metadata import best_thumbnail, clean_title, split_artist_title

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
AUDIO_NATIVE_EXTS = {".m4a", ".mp3"}  # Telegram plays these as proper audio


# ── errors with a user-facing meaning ────────────────────────────────────────
class MediaError(Exception):
    """Base class; ``i18n_key`` maps straight onto a localised message."""

    i18n_key = "error_generic"


class TooLargeError(MediaError):
    i18n_key = "error_too_large"


class PrivateContentError(MediaError):
    i18n_key = "error_private"


class AgeRestrictedError(MediaError):
    i18n_key = "error_age"


class UnavailableError(MediaError):
    i18n_key = "error_unavailable"


class RateLimitedError(MediaError):
    i18n_key = "error_ratelimit"


class BotCheckError(MediaError):
    i18n_key = "error_botcheck"


class FormatUnavailableError(MediaError):
    i18n_key = "error_format"


class UnsupportedError(MediaError):
    i18n_key = "unsupported"


def classify_error(exc: Exception) -> MediaError:
    """Translate yt-dlp's wall of text into something a human can act on."""
    if isinstance(exc, MediaError):
        return exc
    text = str(exc).lower()
    if "too large" in text or "max-filesize" in text or "file too large" in text:
        return TooLargeError(str(exc))
    if "confirm your age" in text or "inappropriate for some users" in text or "age" in text and "sign in" in text:
        return AgeRestrictedError(str(exc))
    if "private" in text or "members-only" in text or "join this channel" in text:
        return PrivateContentError(str(exc))
    if "sign in to confirm" in text or "not a bot" in text:
        return BotCheckError(str(exc))
    if any(s in text for s in ("requested format is not available", "only images are available",
                                "no formats", "requested format not available")):
        return FormatUnavailableError(str(exc))
    if any(s in text for s in ("429", "too many requests", "rate-limit", "rate limit", "login required", "requiring login")):
        return RateLimitedError(str(exc))
    if any(s in text for s in ("unavailable", "isn't available", "no video", "not found", "removed", "404", "unsupported url")):
        return UnavailableError(str(exc))
    return MediaError(str(exc))


# ── YouTube client fallbacks ─────────────────────────────────────────────────
# Datacenter IPs (Hugging Face included) regularly get YouTube's bot-check
# ("Sign in to confirm you're not a bot") or a format list with no playable
# URLs. Other player clients often sail through where the web client fails,
# so extraction/downloads retry through them before giving up.
_YOUTUBE_HINTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "ytsearch")


def _is_youtube_url(url: str) -> bool:
    low = (url or "").lower()
    return any(hint in low for hint in _YOUTUBE_HINTS)


def _client_variants(url: str) -> list[tuple[dict, bool]]:
    """(param overrides, drop cookies?) attempts, mildest first."""
    variants: list[tuple[dict, bool]] = [({}, False)]
    if _is_youtube_url(url):
        for client in ("android_vr", "ios"):
            # These clients don't need (and partly ignore) cookies; dropping
            # them also sidesteps account-bound format restrictions.
            variants.append(({"extractor_args": {"youtube": {"player_client": [client]}}}, True))
    return variants


# Callers may hand us one proxy, a ranked list of them, or none at all;
# internally everything becomes an ordered attempt list ([None] = direct).
ProxyArg = str | list[str] | None

#: Failure phrases that smell like "this exit IP is the problem" — rotating
#: to the next proxy is exactly the cure, so these are retryable too.
_NETWORKISH = ("proxy", "407", "timed out", "timeout", "unable to connect",
               "connection reset", "connection refused", "503", "502",
               "name or service not known", "temporary failure",
               "eof occurred", "ssl", "remote end closed")


def _proxy_attempts(proxy: ProxyArg) -> list[str | None]:
    if isinstance(proxy, str):
        return [proxy] if proxy else [None]
    if proxy:
        return list(proxy)
    return [None]


def _is_retryable(exc: MediaError) -> bool:
    if isinstance(exc, (BotCheckError, FormatUnavailableError, RateLimitedError)):
        return True
    text = str(exc).lower()
    return any(s in text for s in _NETWORKISH)


def _looks_unusable(info: dict) -> bool:
    """True when yt-dlp answered but left us nothing playable (SABR/PO-token)."""
    if info.get("entries"):
        return False
    formats = info.get("formats") or []
    if formats:
        return not any(
            f.get("url") and (f.get("ext") or "").lower() != "mhtml"  # storyboards don't count
            for f in formats
        )
    return not info.get("url")


# ── data transfer objects ────────────────────────────────────────────────────
@dataclass
class SearchResult:
    id: str
    title: str
    uploader: str
    duration: int
    url: str
    thumbnail: str | None = None


@dataclass
class MediaInfo:
    id: str
    title: str
    uploader: str
    duration: int
    webpage_url: str
    extractor: str
    thumbnail: str | None
    has_video: bool
    is_image: bool
    entries: list[dict] = field(default_factory=list)  # carousel / playlist items
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_carousel(self) -> bool:
        return len(self.entries) > 1

    @property
    def cache_base(self) -> str:
        return f"{self.extractor}:{self.id}"


@dataclass
class DownloadedFile:
    path: Path
    title: str
    performer: str = ""
    duration: int = 0
    width: int = 0
    height: int = 0
    thumbnail_url: str | None = None
    kind: str = "video"

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


@dataclass
class Progress:
    percent: float
    speed: str
    eta: str


ProgressCallback = Callable[[Progress], Awaitable[None]]


class ProgressBridge:
    """Thread → event-loop progress reporter, throttled to ~1 edit / 1.4 s."""

    def __init__(self, callback: ProgressCallback | None, max_filesize: int) -> None:
        self._callback = callback
        self._max = max_filesize
        self._last = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def hook(self, d: dict) -> None:  # called by yt-dlp in a worker thread
        if d.get("status") != "downloading":
            return
        downloaded = d.get("downloaded_bytes") or 0
        if downloaded > self._max:  # bail out mid-flight, don't fill the disk
            raise DownloadCancelled("File too large")
        if not self._callback or not self._loop:
            return
        now = time.monotonic()
        if now - self._last < 1.4:
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        self._last = now
        speed = d.get("speed") or 0
        eta = d.get("eta") or 0
        progress = Progress(
            percent=(downloaded * 100 / total) if total else 0.0,
            speed=f"{speed / 1024 / 1024:.1f} MB/s" if speed else "—",
            eta=f"{int(eta)}s" if eta else "—",
        )
        asyncio.run_coroutine_threadsafe(self._safe(progress), self._loop)

    async def _safe(self, progress: Progress) -> None:
        try:
            if self._callback:
                await self._callback(progress)
        except Exception:  # noqa: BLE001 — a failed edit is never fatal
            pass


# ── InnerTube search parsing (pure functions — unit-test friendly) ───────────
_INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/search?prettyPrint=false"
_INNERTUBE_VERSION = "19.44.38"
_RENDERER_KEYS = ("videoRenderer", "compactVideoRenderer")


def _parse_length_text(text: str) -> int:
    """\"3:47\" → 227, \"1:02:33\" → 3753, \"LIVE\"/garbage → 0."""
    parts = (text or "").strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _text_of(node: Any) -> str:
    """InnerTube text nodes come as {simpleText: …} or {runs: [{text: …}]}."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("simpleText"):
        return str(node["simpleText"])
    return "".join(str(run.get("text", "")) for run in node.get("runs") or [])


def _walk(node: Any):
    """Depth-first walk over a JSON blob, in document order (ranking matters)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _renderer_to_result(renderer: dict, max_duration: int) -> SearchResult | None:
    video_id = str(renderer.get("videoId") or "")
    if not video_id:
        return None
    duration = _parse_length_text(_text_of(renderer.get("lengthText")))
    if duration <= 0 or duration > max_duration:
        return None  # live streams & epics don't belong in a song list
    uploader = ""
    for key in ("longBylineText", "shortBylineText", "ownerText"):
        uploader = _text_of(renderer.get(key))
        if uploader:
            break
    thumbs = (renderer.get("thumbnail") or {}).get("thumbnails") or []
    thumb = thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else None
    return SearchResult(
        id=video_id,
        title=clean_title(_text_of(renderer.get("title"))),
        uploader=uploader,
        duration=duration,
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail=thumb or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )


def _find_continuation(data: Any) -> str | None:
    """The token that fetches the next page of results, if there is one."""
    fallback: str | None = None
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        item = node.get("continuationItemRenderer")
        if isinstance(item, dict):  # the results list's own "load more" marker
            endpoint = (item.get("continuationEndpoint") or {}).get("continuationCommand") or {}
            if endpoint.get("token"):
                return str(endpoint["token"])
        command = node.get("continuationCommand")
        if isinstance(command, dict) and command.get("token"):
            fallback = str(command["token"])
        nxt = node.get("nextContinuationData")
        if isinstance(nxt, dict) and nxt.get("continuation"):
            fallback = str(nxt["continuation"])
    return fallback


def _parse_search_response(data: Any, max_duration: int) -> tuple[list[SearchResult], str | None]:
    """Extract (songs, continuation token) from one InnerTube search page."""
    results: list[SearchResult] = []
    by_id: dict[str, int] = {}
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        for key in _RENDERER_KEYS:
            renderer = node.get(key)
            if not isinstance(renderer, dict):
                continue
            parsed = _renderer_to_result(renderer, max_duration)
            if not parsed:
                continue
            if parsed.id in by_id:
                # Same video twice: keep whichever copy carries more metadata.
                idx = by_id[parsed.id]
                if not results[idx].uploader and parsed.uploader:
                    results[idx] = parsed
            else:
                by_id[parsed.id] = len(results)
                results.append(parsed)
    return results, _find_continuation(data)


class Downloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ffmpeg = resolve_ffmpeg()
        self._js_runtime = resolve_js_runtime()
        # Optional outcome hook (url, ok) — app.py wires it to the proxy pool
        # so dead proxies cool down and good ones clear their record.
        self.proxy_reporter: Callable[[str | None, bool], None] | None = None
        self._search_cache: dict[str, tuple[float, list[SearchResult]]] = {}

    def _report_proxy(self, proxy: str | None, ok: bool) -> None:
        if self.proxy_reporter and proxy:
            try:
                self.proxy_reporter(proxy, ok)
            except Exception:  # noqa: BLE001 — bookkeeping must never break a download
                pass

    # ── yt-dlp parameter factory ─────────────────────────────────────────────
    def _base_params(self, *, cookiefile: str | None, proxy: str | None,
                     out_dir: Path | None = None, quiet: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {
            "quiet": quiet,
            "no_warnings": True,
            "noplaylist": False,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,  # parallel chunks = noticeable speed-up
            "http_chunk_size": 16 * 1024 * 1024,
            "max_filesize": self.settings.max_filesize,
            "restrictfilenames": True,
        }
        if out_dir is not None:
            params["outtmpl"] = str(out_dir / "%(id)s.%(ext)s")
        if cookiefile:
            params["cookiefile"] = cookiefile
        if proxy:
            params["proxy"] = proxy
        if self._ffmpeg:
            params["ffmpeg_location"] = self._ffmpeg
        if self._js_runtime:
            params["js_runtimes"] = self._js_runtime
            params["remote_components"] = {"ejs:github"}
        return params

    async def _extract_with_variants(self, url: str, params: dict, *, download: bool = False,
                                     proxies: list[str | None] | None = None) -> dict:
        """Run yt-dlp, rotating proxies and YouTube client fallbacks as needed.

        Order of attempts: best proxy × (default, android_vr, ios), then the
        next proxy, … so one banned exit IP or one bot-checked client never
        ends the story early.
        """
        last: MediaError = UnsupportedError("yt-dlp returned nothing")
        for proxy in proxies or [None]:
            for overrides, drop_cookies in _client_variants(url):
                attempt = dict(params)
                attempt.update(overrides)
                if proxy:
                    attempt["proxy"] = proxy
                else:
                    attempt.pop("proxy", None)
                if drop_cookies:
                    attempt.pop("cookiefile", None)

                def _run(attempt: dict = attempt) -> dict:
                    with yt_dlp.YoutubeDL(attempt) as ydl:
                        return ydl.extract_info(url, download=download) or {}

                try:
                    info = await asyncio.to_thread(_run)
                except DownloadCancelled as exc:
                    raise TooLargeError(str(exc)) from exc
                except DownloadError as exc:
                    last = classify_error(exc)
                    if _is_retryable(last):
                        self._report_proxy(proxy, False)
                        continue  # next client / next proxy may sail through
                    raise last from exc
                if info and not _looks_unusable(info):
                    self._report_proxy(proxy, True)
                    return info
                last = FormatUnavailableError("no usable formats")
        raise last

    # ── extraction (no download) ─────────────────────────────────────────────
    async def extract(self, url: str, *, cookiefile=None, proxy: ProxyArg = None) -> MediaInfo:
        params = self._base_params(cookiefile=cookiefile, proxy=None)
        params["extract_flat"] = "in_playlist"
        info = await self._extract_with_variants(url, params, proxies=_proxy_attempts(proxy))
        return self._to_media_info(info, fallback_url=url)

    def _to_media_info(self, info: dict, fallback_url: str = "") -> MediaInfo:
        entries = [e for e in (info.get("entries") or []) if e]
        main = info
        if entries and info.get("_type") == "playlist" and len(entries) == 1:
            main = entries[0]  # a "playlist" of one is just a track in a trench coat
            entries = []

        formats = main.get("formats") or []
        has_video = any((f.get("vcodec") or "none") != "none" for f in formats)
        ext = f".{(main.get('ext') or '').lower()}"
        if not has_video and ext in VIDEO_EXTS:
            has_video = True
        is_image = ext in IMAGE_EXTS or (
            bool(formats)
            and all(f".{(f.get('ext') or '').lower()}" in IMAGE_EXTS for f in formats)
        )
        performer, title = split_artist_title(main)
        return MediaInfo(
            id=str(main.get("id") or info.get("id") or ""),
            title=title or clean_title(str(main.get("title") or "")),
            uploader=performer,
            duration=int(main.get("duration") or 0),
            webpage_url=str(main.get("webpage_url") or fallback_url),
            extractor=str(main.get("extractor_key") or main.get("extractor") or "generic").lower(),
            thumbnail=best_thumbnail(main),
            has_video=has_video,
            is_image=is_image and not has_video,
            entries=entries[: self.settings.carousel_limit] if len(entries) > 1 else [],
            raw=main,
        )

    # ── YouTube search ───────────────────────────────────────────────────────
    async def search(self, query: str, *, cookiefile=None, proxy: ProxyArg = None) -> list[SearchResult]:
        """Search YouTube, keep only tracks ≤ ``search_max_duration`` seconds.

        Fast path: one InnerTube JSON call (≈0.3–1 s) instead of a full
        yt-dlp ``ytsearch`` extraction (often 5–20 s). yt-dlp stays as the
        fallback; identical queries are cached for a few minutes either way.
        """
        cache_key = " ".join((query or "").lower().split())
        cached = self._search_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 600:
            return list(cached[1])

        attempts = _proxy_attempts(proxy)
        results: list[SearchResult] = []
        try:
            results = await self._innertube_search(query, attempts)
        except MediaError:
            results = []  # → yt-dlp below; InnerTube hiccups must not break search
        if not results:
            results = await self._search_via_ytdlp(query, cookiefile=cookiefile, attempts=attempts)

        if results:
            self._search_cache[cache_key] = (time.monotonic(), results)
            if len(self._search_cache) > 64:  # tiny cache, evict the oldest
                self._search_cache.pop(next(iter(self._search_cache)))
        return results

    async def _search_via_ytdlp(self, query: str, *, cookiefile,
                                attempts: list[str | None]) -> list[SearchResult]:
        fetch = self.settings.search_results + 15  # headroom for filtered-out long videos
        params = self._base_params(cookiefile=cookiefile, proxy=None)
        params.update({"extract_flat": True, "noplaylist": True})

        data = await self._extract_with_variants(
            f"ytsearch{fetch}:{query}", params, proxies=attempts)

        results: list[SearchResult] = []
        seen: set[str] = set()
        for entry in data.get("entries") or []:
            if not entry or not entry.get("id") or entry["id"] in seen:
                continue
            duration = int(entry.get("duration") or 0)
            if duration <= 0 or duration > self.settings.search_max_duration:
                continue  # songs only — no 3-hour "lofi to cry to" compilations
            seen.add(entry["id"])
            thumbs = entry.get("thumbnails") or [{}]
            results.append(SearchResult(
                id=str(entry["id"]),
                title=clean_title(str(entry.get("title") or "")),
                uploader=str(entry.get("uploader") or entry.get("channel") or ""),
                duration=duration,
                url=f"https://www.youtube.com/watch?v={entry['id']}",
                thumbnail=thumbs[-1].get("url") if thumbs else None,
            ))
            if len(results) >= self.settings.search_results:
                break
        return results

    async def _innertube_search(self, query: str,
                                attempts: list[str | None]) -> list[SearchResult]:
        """One-shot search via YouTube's internal ANDROID client.

        The ANDROID InnerTube client needs no API key, no PoToken and no
        consent dance, and answers in well under a second — by far the
        fastest way to search without the official quota-guarded Data API.
        Raises MediaError when every exit fails, so search() can fall back.
        """
        target = self.settings.search_results
        context = {"client": {
            "clientName": "ANDROID",
            "clientVersion": _INNERTUBE_VERSION,
            "androidSdkVersion": 34,
            "hl": "en", "gl": "US", "utcOffsetMinutes": 0,
        }}
        headers = {
            "Content-Type": "application/json",
            "X-YouTube-Client-Name": "3",  # 3 = ANDROID
            "X-YouTube-Client-Version": _INNERTUBE_VERSION,
            "User-Agent": f"com.google.android.youtube/{_INNERTUBE_VERSION} "
                          "(Linux; U; Android 14; en_US; Pixel 8 Pro)",
        }
        last_error: Exception | None = None
        for proxy in attempts:
            try:
                results: list[SearchResult] = []
                seen: set[str] = set()
                payload: dict[str, Any] = {"context": context, "query": query}
                async with proxy_session(proxy, timeout=20, headers=headers) as (session, req_proxy):
                    for _page in range(3):  # first page + up to 2 continuations
                        async with session.post(_INNERTUBE_URL, json=payload,
                                                proxy=req_proxy) as resp:
                            if resp.status != 200:
                                raise MediaError(f"innertube HTTP {resp.status}")
                            data = await resp.json(content_type=None)
                        fresh, token = _parse_search_response(
                            data, self.settings.search_max_duration)
                        for item in fresh:
                            if item.id not in seen:
                                seen.add(item.id)
                                results.append(item)
                        if len(results) >= target or not token:
                            break
                        payload = {"context": context, "continuation": token}
                if results:
                    self._report_proxy(proxy, True)
                    return results[:target]
                last_error = MediaError("innertube returned nothing usable")
            except MediaError as exc:
                last_error = exc
                self._report_proxy(proxy, False)
            except Exception as exc:  # noqa: BLE001 — try the next exit IP
                last_error = exc
                self._report_proxy(proxy, False)
        raise MediaError(f"innertube search failed: {last_error}")

    # ── downloads ────────────────────────────────────────────────────────────
    async def download_video(self, url: str, out_dir: Path, *, cookiefile=None, proxy: ProxyArg = None,
                             quality: str = "720", on_progress: ProgressCallback | None = None) -> DownloadedFile:
        height_cap = {"best": None, "1080": 1080, "720": 720, "480": 480, "360": 360}.get(quality, 720)
        h = f"[height<={height_cap}]" if height_cap else ""
        # H.264 MP4 first — it plays everywhere Telegram does.
        fmt = (
            f"bv*{h}[ext=mp4][vcodec^=avc]+ba[ext=m4a]/b{h}[ext=mp4]/"
            f"bv*{h}+ba/b{h}/best"
        )
        params = self._base_params(cookiefile=cookiefile, proxy=None, out_dir=out_dir)
        params.update({
            "format": fmt,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "progress_hooks": [ProgressBridge(on_progress, self.settings.max_filesize).hook],
        })
        info = await self._download(url, params, out_dir, proxies=_proxy_attempts(proxy))
        performer, title = split_artist_title(info)
        return DownloadedFile(
            path=self._result_path(info, out_dir), title=title, performer=performer,
            duration=int(info.get("duration") or 0),
            width=int(info.get("width") or 0), height=int(info.get("height") or 0),
            thumbnail_url=best_thumbnail(info), kind="video",
        )

    async def download_audio(self, url: str, out_dir: Path, *, cookiefile=None, proxy: ProxyArg = None,
                             on_progress: ProgressCallback | None = None) -> DownloadedFile:
        """Grab the best audio stream in whatever format the site offers.

        Preference order is Telegram-native first (m4a/mp3), then literally
        any audio the page has — exotic containers are normalised afterwards
        instead of failing with "format is not available".
        """
        params = self._base_params(cookiefile=cookiefile, proxy=None, out_dir=out_dir)
        params.update({
            "format": "ba[ext=m4a]/ba[ext=mp3]/ba[ext=aac]/ba/bestaudio/b/best",
            "noplaylist": True,
            "progress_hooks": [ProgressBridge(on_progress, self.settings.max_filesize).hook],
        })
        info = await self._download(url, params, out_dir, proxies=_proxy_attempts(proxy))
        path = self._result_path(info, out_dir)
        performer, title = split_artist_title(info)

        if path.suffix.lower() not in AUDIO_NATIVE_EXTS:
            converted = await self._to_telegram_audio(path)
            if converted != path:
                path.unlink(missing_ok=True)
                path = converted
        return DownloadedFile(
            path=path, title=title, performer=performer,
            duration=int(info.get("duration") or 0),
            thumbnail_url=best_thumbnail(info), kind="audio",
        )

    async def download_carousel(self, info: MediaInfo, out_dir: Path, *, cookiefile=None,
                                proxy: ProxyArg = None, on_progress: ProgressCallback | None = None) -> list[DownloadedFile]:
        """Download every item of a carousel/playlist post (capped, best-effort)."""
        files: list[DownloadedFile] = []
        for entry in info.entries:
            entry_url = entry.get("webpage_url") or entry.get("url") or ""
            if not entry_url:
                continue
            params = self._base_params(cookiefile=cookiefile, proxy=None, out_dir=out_dir)
            params.update({"format": "b[ext=mp4]/best", "noplaylist": True,
                           "progress_hooks": [ProgressBridge(on_progress, self.settings.max_filesize).hook]})
            try:
                sub = await self._download(entry_url, params, out_dir, proxies=_proxy_attempts(proxy))
            except MediaError:
                continue  # one rotten slide shouldn't spoil the whole carousel
            path = self._result_path(sub, out_dir)
            ext = path.suffix.lower()
            kind = "video" if ext in VIDEO_EXTS else "photo" if ext in IMAGE_EXTS else "document"
            files.append(DownloadedFile(
                path=path, title=info.title, duration=int(sub.get("duration") or 0),
                width=int(sub.get("width") or 0), height=int(sub.get("height") or 0), kind=kind,
            ))
        return files

    async def download_image(self, url: str, out_dir: Path, *, cookiefile=None, proxy: ProxyArg = None) -> DownloadedFile:
        params = self._base_params(cookiefile=cookiefile, proxy=None, out_dir=out_dir)
        params.update({"format": "best", "noplaylist": True})
        info = await self._download(url, params, out_dir, proxies=_proxy_attempts(proxy))
        return DownloadedFile(
            path=self._result_path(info, out_dir),
            title=clean_title(str(info.get("title") or "photo")), kind="photo",
        )

    # ── internals ────────────────────────────────────────────────────────────
    async def _download(self, url: str, params: dict, out_dir: Path,
                        proxies: list[str | None] | None = None) -> dict:
        info = await self._extract_with_variants(url, params, download=True, proxies=proxies)
        # Playlists sneaking through: take the first downloaded entry.
        if info.get("_type") == "playlist" and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        self._result_path(info, out_dir)  # raises early with a friendly error
        return info

    @staticmethod
    def _result_path(info: dict, out_dir: Path) -> Path:
        for req in info.get("requested_downloads") or []:
            fp = req.get("filepath")
            if fp and Path(fp).is_file():
                return Path(fp)
        fp = info.get("_filename") or info.get("filepath")
        if fp and Path(str(fp)).is_file():
            return Path(str(fp))
        # StockTaking: newest file in the job dir is almost certainly ours.
        candidates = [p for p in out_dir.iterdir() if p.is_file() and p.suffix != ".part"]
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        raise UnsupportedError("download produced no file")

    async def _run_ffmpeg(self, args: list[str], timeout: int = 600) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg, *args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await asyncio.wait_for(proc.wait(), timeout=timeout) == 0
        except TimeoutError:
            proc.kill()
            return False

    async def _audio_codec(self, src: Path) -> str | None:
        """Name of the first audio codec in a file, via ffmpeg's own report."""
        if not self._ffmpeg:
            return None
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg, "-i", str(src),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        match = re.search(rb"Audio: ([A-Za-z0-9_]+)", err or b"")
        return match.group(1).decode().lower() if match else None

    async def _to_telegram_audio(self, src: Path) -> Path:
        """Normalise exotic audio into a Telegram-native container.

        Telegram treats only MP3/M4A as proper audio. AAC/MP3 streams hiding
        in odd containers are remuxed bit-for-bit (fast, lossless); anything
        else (opus, webm, vorbis…) is transcoded to M4A/AAC, MP3 as backup.
        Returns the original path when conversion isn't possible — better to
        try sending *something* than to fail the whole request.
        """
        if not self._ffmpeg or src.suffix.lower() in AUDIO_NATIVE_EXTS:
            return src
        codec = await self._audio_codec(src)
        if codec == "aac":
            dst = src.with_suffix(".m4a")
            if await self._run_ffmpeg(["-y", "-i", str(src), "-vn", "-c:a", "copy", str(dst)]):
                return dst
        if codec == "mp3":
            dst = src.with_suffix(".mp3")
            if await self._run_ffmpeg(["-y", "-i", str(src), "-vn", "-c:a", "copy", str(dst)]):
                return dst
        dst = src.with_suffix(".m4a")
        if await self._run_ffmpeg(["-y", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "192k", str(dst)]):
            return dst
        dst = src.with_suffix(".mp3")
        if await self._run_ffmpeg(["-y", "-i", str(src), "-vn", "-b:a", "192k", str(dst)]):
            return dst
        return src


def ytdlp_version() -> str:
    try:
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return "unknown"
