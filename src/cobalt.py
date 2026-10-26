"""Cobalt API client — the fast lane for Instagram/TikTok/X/Pinterest & co.

yt-dlp keeps YouTube and audio duties; everything social goes through a
Cobalt instance first (public ``api.cobalt.tools`` by default, or your own
via COBALT_API_URL). Cobalt is purpose-built for these sites, returns
direct/tunnel URLs in one POST, and handles carousels as picker items:
https://github.com/imputnet/cobalt/blob/main/docs/api.md

Any failure raises MediaError and the caller falls back to yt-dlp/gallery-dl,
so Cobalt being down can never make things worse than before.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from .config import Settings, resolve_ffmpeg
from .downloader import DownloadedFile, MediaError, TooLargeError
from .httputil import proxy_session
from .metadata import clean_title

log = logging.getLogger("musicbot.cobalt")

#: Host suffixes Cobalt handles well (YouTube deliberately excluded).
COBALT_HOSTS: tuple[str, ...] = (
    "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "facebook.com", "fb.watch", "pinterest.com", "pinterest.co.uk",
    "pin.it", "reddit.com", "vimeo.com", "snapchat.com", "tumblr.com",
    "twitch.tv", "soundcloud.com", "bilibili.com", "bsky.app",
    "dailymotion.com", "vk.com", "ok.ru", "rutube.ru", "streamable.com",
    "loom.com", "xiaohongshu.com",
)

_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".ogg", ".wav"}
_CT_EXT = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
    "audio/opus": ".opus", "audio/ogg": ".ogg", "audio/wav": ".wav",
}
_QUALITY_OK = {"max", "4320", "2160", "1440", "1080", "720", "480", "360", "240", "144"}


def is_cobalt_url(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in COBALT_HOSTS)


def _safe_stem(filename: str, fallback: str) -> str:
    stem = Path(filename or "").stem or fallback
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or fallback
    return stem[:60]


def _kind_for_ext(ext: str, hint: str | None = None) -> str:
    if hint in {"photo", "video", "gif"}:
        return "photo" if hint == "photo" else "video"
    if ext in _IMAGE_EXTS:
        return "photo"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "video"


class CobaltClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ffmpeg = resolve_ffmpeg()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.cobalt_enabled and self.settings.cobalt_api_url)

    # ── API call ─────────────────────────────────────────────────────────────
    async def _post(self, url: str, *, quality: str, proxies: list[str | None]) -> dict:
        payload = {
            "url": url,
            "videoQuality": quality if quality in _QUALITY_OK else "720",
            "downloadMode": "auto",
            "filenameStyle": "basic",
            "alwaysProxy": True,  # tunnel URLs dodge CDN blocks on our IP too
        }
        headers = {"Accept": "application/json"}  # cobalt refuses anything else
        if self.settings.cobalt_api_key:
            headers["Authorization"] = f"Api-Key {self.settings.cobalt_api_key}"
        last_error: Exception | None = None
        for proxy in proxies or [None]:
            try:
                async with proxy_session(proxy, timeout=45, headers=headers) as (session, req_proxy):
                    async with session.post(self.settings.cobalt_api_url,
                                            json=payload, proxy=req_proxy) as resp:
                        data = await resp.json(content_type=None)
                        if resp.status >= 400:
                            code = (data.get("error") or {}).get("code", resp.status)
                            raise MediaError(f"cobalt HTTP {resp.status}: {code}")
                        return data
            except MediaError:
                raise
            except Exception as exc:  # noqa: BLE001 — try the next exit IP
                last_error = exc
        raise MediaError(f"cobalt unreachable: {last_error}")

    # ── file downloads ───────────────────────────────────────────────────────
    async def _download_one(self, file_url: str, dest_base: Path, *,
                            proxies: list[str | None]) -> Path:
        last_error: Exception | None = None
        for proxy in proxies or [None]:
            try:
                async with proxy_session(proxy, timeout=300) as (session, req_proxy):
                    async with session.get(file_url, proxy=req_proxy) as resp:
                        if resp.status != 200:
                            raise MediaError(f"cobalt file HTTP {resp.status}")
                        ext = (Path(urlsplit(file_url).path).suffix or "").lower()
                        if ext not in _VIDEO_EXTS | _IMAGE_EXTS | _AUDIO_EXTS:
                            ext = _CT_EXT.get((resp.content_type or "").lower(), ".mp4")
                        dest = dest_base.with_suffix(ext)
                        written = 0
                        with dest.open("wb") as fh:
                            async for chunk in resp.content.iter_chunked(256 * 1024):
                                written += len(chunk)
                                if written > self.settings.max_filesize:
                                    fh.close()
                                    dest.unlink(missing_ok=True)
                                    raise TooLargeError("cobalt file too large")
                                fh.write(chunk)
                        if written == 0:
                            raise MediaError("cobalt returned an empty file")
                        return dest
            except (MediaError, TooLargeError):
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise MediaError(f"cobalt download failed: {last_error}")

    async def _merge(self, parts: list[Path], out_name: str, out_dir: Path) -> Path:
        """local-processing 'merge': mux separate video+audio tunnels locally."""
        if not self._ffmpeg or len(parts) < 2:
            return parts[0]
        out = out_dir / f"{_safe_stem(out_name, 'merged')}.mp4"
        cmd = [self._ffmpeg, "-y"]
        for part in parts[:2]:
            cmd += ["-i", str(part)]
        cmd += ["-c", "copy", str(out)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=600)
        except TimeoutError:
            proc.kill()
            return parts[0]
        return out if out.is_file() and out.stat().st_size > 0 else parts[0]

    # ── main entry ───────────────────────────────────────────────────────────
    async def fetch(self, url: str, out_dir: Path, *, quality: str = "720",
                    proxies: list[str | None] | None = None,
                    limit: int = 20) -> list[DownloadedFile]:
        attempts: list[str | None] = list(proxies or []) or [None]
        data = await self._post(url, quality=quality, proxies=attempts)
        status = data.get("status")

        if status == "error":
            code = (data.get("error") or {}).get("code", "unknown")
            raise MediaError(f"cobalt error: {code}")

        if status in ("tunnel", "redirect"):
            filename = str(data.get("filename") or "cobalt_file")
            dest = out_dir / _safe_stem(filename, "cobalt_file")
            path = await self._download_one(str(data["url"]), dest, proxies=attempts)
            title = clean_title(Path(filename).stem.replace("_", " "))
            return [DownloadedFile(path=path, title=title,
                                   kind=_kind_for_ext(path.suffix.lower()))]

        if status == "picker":
            files: list[DownloadedFile] = []
            for idx, item in enumerate((data.get("picker") or [])[:limit]):
                item_url = item.get("url")
                if not item_url:
                    continue
                dest = out_dir / f"item_{idx:03d}"
                try:
                    path = await self._download_one(str(item_url), dest, proxies=attempts)
                except Exception:  # noqa: BLE001 — a broken slide mustn't kill the album
                    continue
                files.append(DownloadedFile(
                    path=path, title="",
                    kind=_kind_for_ext(path.suffix.lower(), item.get("type"))))
            if not files:
                raise MediaError("cobalt picker delivered nothing")
            return files

        if status == "local-processing":
            tunnels = [str(u) for u in data.get("tunnel") or []]
            if not tunnels:
                raise MediaError("cobalt local-processing without tunnels")
            parts: list[Path] = []
            for idx, tunnel in enumerate(tunnels[:3]):
                parts.append(await self._download_one(
                    tunnel, out_dir / f"part_{idx}", proxies=attempts))
            output = data.get("output") or {}
            out_name = str(output.get("filename") or "cobalt_file")
            if data.get("type") == "merge" and len(parts) >= 2:
                final = await self._merge(parts, out_name, out_dir)
            else:
                final = parts[0]
            kind = "audio" if data.get("type") == "audio" else _kind_for_ext(final.suffix.lower())
            title = clean_title(Path(out_name).stem.replace("_", " "))
            return [DownloadedFile(path=final, title=title, kind=kind)]

        raise MediaError(f"unexpected cobalt status: {status!r}")
