"""Music recognition — 'what song is playing in this video?'

Pipeline: pull a 14-second audio snippet from the middle of the media with
ffmpeg (the middle is where the chorus usually lives), then ask Shazam.
Free, no API key, surprisingly good ears.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .config import resolve_ffmpeg

_SNIPPET_SECONDS = 14


@dataclass
class RecognizedTrack:
    title: str
    artist: str
    album: str = ""
    cover_url: str | None = None
    shazam_url: str | None = None

    @property
    def query(self) -> str:
        return f"{self.artist} {self.title}".strip()


async def _probe_duration(ffmpeg: str, media: Path) -> float:
    """Duration in seconds via ffmpeg's stderr (ffprobe may not exist here)."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-i", str(media),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode(errors="ignore")
    for line in text.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            try:
                h, m, s = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                return 0.0
    return 0.0


async def extract_snippet(media: Path, out_dir: Path) -> Path | None:
    """Cut a mono MP3 snippet suitable for fingerprinting."""
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    duration = await _probe_duration(ffmpeg, media)
    start = max(0.0, (duration - _SNIPPET_SECONDS) / 2) if duration > _SNIPPET_SECONDS else 0.0
    dst = out_dir / "snippet.mp3"
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-ss", f"{start:.1f}", "-i", str(media),
        "-t", str(_SNIPPET_SECONDS), "-vn", "-ac", "1", "-ar", "44100", str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=120)
    except TimeoutError:
        proc.kill()
        return None
    return dst if dst.is_file() and dst.stat().st_size > 0 else None


async def recognize_file(media: Path, work_dir: Path) -> RecognizedTrack | None:
    """Recognise the track in an audio/video file. None = Shazam shrugged."""
    snippet = await extract_snippet(media, work_dir)
    target = snippet or media
    try:
        from shazamio import Shazam

        result = await asyncio.wait_for(Shazam().recognize(str(target)), timeout=60)
    except Exception:  # noqa: BLE001 — network hiccups shouldn't crash the bot
        return None

    track = (result or {}).get("track") if isinstance(result, dict) else None
    if not track:
        return None
    images = track.get("images") or {}
    album = ""
    for section in track.get("sections") or []:
        for row in section.get("metadata") or []:
            if row.get("title", "").lower() == "album":
                album = row.get("text", "")
    return RecognizedTrack(
        title=str(track.get("title") or "").strip(),
        artist=str(track.get("subtitle") or "").strip(),
        album=album,
        cover_url=images.get("coverart") or images.get("background"),
        shazam_url=track.get("url"),
    )
