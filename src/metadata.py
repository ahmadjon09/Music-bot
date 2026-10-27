"""Title cleanup, artist/title splitting and audio tagging.

Raw YouTube titles look like marketing departments fighting each other:
``"Drake - God's Plan (Official Music Video) [4K] ft. Nobody"``.
Here we turn them into a clean ``performer`` / ``title`` pair and stamp the
file with proper ID3/MP4 tags + cover art so every player shows it nicely.
"""

from __future__ import annotations

import re
from pathlib import Path

# Noise we strip wherever it appears inside () or [] brackets.
_NOISE = (
    r"official\s*(music\s*)?video|official\s*audio|official\s*lyric\w*|lyrics?|"
    r"music\s*video|video\s*clip|official\s*(mv|clip)|\bmv\b|hd|hq|4k|8k|1080p?|720p?|"
    r"remaster(ed)?(\s*\d{4})?|audio|video|full\s*song|premiere|trailer|teaser|"
    r"visualizer|color\s*coded\s*lyrics?|премьера(\s+клипа)?|клип|видеоклип|"
    r"premyera|rasmiy(\s+klip)?|prod\.\s*by\s*[\w\s]+|dir\.\s*by\s*[\w\s]+"
)
_BRACKET_NOISE_RE = re.compile(rf"[\(\[][^\)\]]*({_NOISE})[^\)\]]*[\)\]]", re.IGNORECASE)
_EMPTY_BRACKETS_RE = re.compile(r"[\(\[]\s*[\)\]]")
_SUFFIX_RE = re.compile(
    r"\s*[-|•·]\s*(official\s*(music\s*)?video|official\s*audio|lyrics?|hd|4k)\s*$", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s{2,}")
_DANGLING_RE = re.compile(r"[\s\-_–—|•·:]+$|^[\s\-_–—|•·:]+")
# Unbracketed tails: "… Official Music Video", "… HD", "… Music Video".
# Deliberately conservative — a song genuinely called "Video" survives,
# because we only strip official/combo/quality phrases.
_TRAILING_RES = (
    re.compile(r"\s+official\s+(music\s+)?(video|audio|mv|clip|lyrics?\s*video)\s*$", re.IGNORECASE),
    re.compile(r"\s+(music\s+video|lyrics?\s*video|премьера\s+клипа)\s*$", re.IGNORECASE),
    re.compile(r"\s+(full\s*)?(hd|hq|4k|8k|2160p|1080p|720p)\s*$", re.IGNORECASE),
)
# Leading shouts: "Премьера клипа! Artist - Song", "PREMIERE: …"
_LEADING_RE = re.compile(r"^(премьера(\s+клипа)?|premiere|premyera)[!:\s\-–—]*", re.IGNORECASE)


def clean_title(raw: str) -> str:
    """Strip the usual YouTube glitter from a title."""
    title = (raw or "").strip()
    if not title:
        return "Unknown title"
    title = _LEADING_RE.sub("", title)
    # Run a few times: nested junk like "(Official Video) [HD]" peels layer by layer.
    for _ in range(3):
        title = _BRACKET_NOISE_RE.sub(" ", title)
        title = _SUFFIX_RE.sub("", title)
        for pattern in _TRAILING_RES:
            title = pattern.sub("", title)
    title = _EMPTY_BRACKETS_RE.sub(" ", title)
    title = _WHITESPACE_RE.sub(" ", title)
    title = _DANGLING_RE.sub("", title).strip()
    return title or (raw.strip() or "Unknown title")


def _clean_artist(raw: str) -> str:
    artist = (raw or "").strip()
    for suffix in (" - Topic", "VEVO", "Official", " TV", " Music"):
        if artist.lower().endswith(suffix.lower()) and len(artist) > len(suffix) + 1:
            artist = artist[: -len(suffix)].strip()
    return artist


def split_artist_title(info: dict) -> tuple[str, str]:
    """Best-effort (performer, title) from a yt-dlp info dict."""
    track = (info.get("track") or "").strip()
    artist = (info.get("artist") or info.get("creator") or "").strip()
    if track and artist:
        # First artist only — "feat." chains make filenames unreadable.
        primary = re.split(r",|&|feat\.?|ft\.?", artist, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return primary, clean_title(track)

    title = clean_title(info.get("title") or track)
    uploader = _clean_artist(info.get("uploader") or info.get("channel") or "")

    # The classic "Artist - Title" layout covers most music uploads.
    for sep in (" - ", " – ", " — ", " | ", ": "):
        if sep in title:
            left, right = title.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right and len(left) <= 60:
                return left, right
            break
    return uploader or "Unknown artist", title


_FILENAME_BAD_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def media_filename(title: str, performer: str, ext: str) -> str:
    """Human-friendly download name, e.g. ``Rick Astley - Never Gonna….m4a``.

    Telegram shows this as the saved file name when a user downloads the
    track — a raw video id would be pure user-hostile.
    """
    base = f"{performer} - {title}" if performer and performer != "Unknown artist" else title
    base = _WHITESPACE_RE.sub(" ", _FILENAME_BAD_RE.sub(" ", base)).strip(" .")
    base = base[:90].rstrip(" .") or "track"
    return f"{base}.{ext.lstrip('.').lower()}"


def best_thumbnail(info: dict) -> str | None:
    """Pick the largest JPEG-ish thumbnail URL from an info dict."""
    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return info.get("thumbnail")
    scored = []
    for thumb in thumbs:
        url = thumb.get("url") or ""
        if not url:
            continue
        area = int(thumb.get("width") or 0) * int(thumb.get("height") or 0)
        scored.append((area, url))
    scored.sort(reverse=True)
    return scored[0][1] if scored else info.get("thumbnail")


def prepare_cover(image_bytes: bytes, *, square: bool = True, max_size: int = 640) -> bytes | None:
    """Convert arbitrary thumbnail bytes to a clean JPEG (optionally square)."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if square:  # center-crop — album art looks right in every player
            side = min(img.size)
            x, y = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((x, y, x + side, y + side))
        img.thumbnail((max_size, max_size))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — a broken cover must never break a download
        return None


def tag_audio(path: Path, title: str, performer: str, cover_jpeg: bytes | None) -> None:
    """Write title/artist/cover into an MP3 or M4A file, in place."""
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import APIC, ID3, TIT2, TPE1
            from mutagen.mp3 import MP3

            audio = MP3(str(path))
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TIT2(encoding=3, text=title))
            audio.tags.add(TPE1(encoding=3, text=performer))
            if cover_jpeg:
                audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_jpeg))
            audio.save()
        elif ext in {".m4a", ".mp4", ".aac"}:
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(str(path))
            audio["\xa9nam"] = [title]
            audio["\xa9ART"] = [performer]
            audio["aART"] = [performer]
            if cover_jpeg:
                audio["covr"] = [MP4Cover(cover_jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
    except Exception:  # noqa: BLE001 — untagged audio still sounds the same
        return


def audio_duration(path: Path) -> int:
    """Duration in whole seconds (0 when unreadable)."""
    try:
        from mutagen import File as MutagenFile

        meta = MutagenFile(str(path))
        return int(meta.info.length) if meta and meta.info else 0
    except Exception:  # noqa: BLE001
        return 0


def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "–:––"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def prepare_telegram_thumbnail(image_bytes: bytes, *, square: bool = False,
                               max_size: int = 320, max_bytes: int = 200_000) -> bytes | None:
    """Create a JPEG thumbnail within Telegram's 320px / 200 KB limits."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if square:
            side = min(img.size)
            x, y = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((x, y, x + side, y + side))
        img.thumbnail((max_size, max_size))
        for quality in (88, 78, 68, 58, 48, 38):
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            data = out.getvalue()
            if len(data) <= max_bytes:
                return data
        # Rare noisy photos can still exceed the cap at low quality. Shrink
        # once more rather than making Telegram reject an otherwise good song.
        img.thumbnail((max(1, max_size // 2), max(1, max_size // 2)))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=55, optimize=True)
        data = out.getvalue()
        return data if len(data) <= max_bytes else None
    except Exception:  # noqa: BLE001 — a missing cover must never block media
        return None
