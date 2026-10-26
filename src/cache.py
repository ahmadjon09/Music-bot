"""Canonical cache keys — the heart of the "instant re-send" trick.

The same media arrives through wildly different URLs:
``youtu.be/abc?si=x`` ≡ ``youtube.com/watch?v=abc`` ≡ ``youtube.com/shorts/abc``.
Canonicalisation collapses all of them into one stable key like
``youtube:dQw4w9WgXcQ``, so a track downloaded by *any* user is re-sent to
everyone else straight from Telegram's own servers (by ``file_id``) —
no yt-dlp, no disk, no waiting. That's the whole game.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

# Query parameters that never change *which* media a URL points to.
_TRACKING_PARAMS = {
    "si", "feature", "igsh", "igshid", "fbclid", "gclid", "mc_cid", "mc_eid",
    "s", "t", "ref", "ref_src", "ref_url", "spm", "share_id", "sender_device",
    "is_from_webapp", "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "_branch_match_id", "nd", "d", "ctx", "lang", "hl",
}

_YOUTUBE_ID = r"([A-Za-z0-9_-]{11})"
# IGNORECASE matches hosts in any spelling, while captured IDs keep their
# original case — YouTube/Instagram IDs are case-sensitive, lowercasing them
# would silently point the key at a *different* media item.
_YT_PATTERNS = (
    re.compile(rf"youtu\.be/{_YOUTUBE_ID}", re.IGNORECASE),
    re.compile(rf"youtube(?:-nocookie)?\.com/(?:shorts|live|embed|v|clip)/{_YOUTUBE_ID}", re.IGNORECASE),
    re.compile(rf"youtube(?:-nocookie)?\.com/watch\?[^#]*\bv={_YOUTUBE_ID}", re.IGNORECASE),
    re.compile(rf"youtube(?:-nocookie)?\.com/attribution_link\?[^#]*\bv%3D{_YOUTUBE_ID}", re.IGNORECASE),
)
_INSTAGRAM_RE = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE)
_TIKTOK_RE = re.compile(r"tiktok\.com/(?:@[^/]+/)?(?:video|photo)/(\d+)", re.IGNORECASE)
_TWITTER_RE = re.compile(r"(?:twitter\.com|x\.com)/[^/]+/status/(\d+)", re.IGNORECASE)
_PINTEREST_RE = re.compile(r"pinterest\.[a-z.]+/pin/(\d+)", re.IGNORECASE)
_PINTEREST_PATH_RE = re.compile(r"pinterest\.[a-z.]+/pin/[^/]*--(\d+)", re.IGNORECASE)
_FACEBOOK_RE = re.compile(r"facebook\.com/(?:watch\?v=|[^/]+/videos/)(\d+)", re.IGNORECASE)
_VIMEO_RE = re.compile(r"vimeo\.com/(\d+)", re.IGNORECASE)


def _first(patterns, text: str) -> str | None:
    for pattern in patterns:
        if match := pattern.search(text):
            return match.group(1)
    return None


def canonicalize_url(url: str) -> str:
    """Collapse every known URL spelling of a media item into ONE cache key."""
    raw = (url or "").strip()

    if vid := _first(_YT_PATTERNS, raw):
        return f"youtube:{vid}"
    if match := _INSTAGRAM_RE.search(raw):
        return f"instagram:{match.group(1)}"
    if match := _TIKTOK_RE.search(raw):
        return f"tiktok:{match.group(1)}"
    if match := _TWITTER_RE.search(raw):
        return f"twitter:{match.group(1)}"
    if match := _PINTEREST_PATH_RE.search(raw) or _PINTEREST_RE.search(raw):
        return f"pinterest:{match.group(1)}"
    if match := _FACEBOOK_RE.search(raw):
        return f"facebook:{match.group(1)}"
    if match := _VIMEO_RE.search(raw):
        return f"vimeo:{match.group(1)}"
    if "soundcloud.com/" in raw.lower():
        path = urlsplit(raw).path.strip("/").lower()  # SoundCloud slugs are lowercase
        if path:
            return f"soundcloud:{path}"

    # Short links (vm.tiktok.com, pin.it, fb.watch…) can't be resolved without
    # a network hop — keep a normalised spelling; the post-extract
    # "extractor:id" key covers the resolved form after the first download.
    return f"url:{normalize_url(raw)}"


def normalize_url(url: str) -> str:
    """Lower-case host, drop tracking params, sort the rest, trim slashes."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in {"http", "https", ""} else parts.scheme
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/") or "/"
    keep = [(k, v) for k, v in parse_qsl(parts.query)
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    query = urlencode(sorted(keep))
    base = f"{scheme}://{host}{path}"
    return f"{base}?{query}" if query else base


# ── key builders (single source of truth for the cache layout) ──────────────
def audio_key(canonical: str) -> str:
    return f"{canonical}|audio"


def video_key(canonical: str, quality: str) -> str:
    # Quality is part of the key: a 360p user must not be ambushed by a
    # cached 1080p file just because it happens to exist.
    return f"{canonical}|video|{quality}"


def photo_key(canonical: str) -> str:
    return f"{canonical}|photo"


def upload_audio_key(file_unique_id: str) -> str:
    return f"upload:{file_unique_id}|audio"


def extractor_key(extractor: str, media_id: str) -> str:
    """Normalise a yt-dlp (extractor, id) pair into our canonical spelling."""
    name = (extractor or "generic").lower()
    aliases = {"youtube": "youtube", "tiktok": "tiktok", "instagram": "instagram",
               "twitter": "twitter", "pinterest": "pinterest", "facebook": "facebook",
               "vimeo": "vimeo", "soundcloud": "soundcloud"}
    return f"{aliases.get(name, name)}:{media_id}"


def all_keys(canonical: str, extracted: str | None) -> list[str]:
    """Every canonical spelling worth storing/looking up for one media item."""
    keys = [canonical]
    if extracted and extracted not in keys:
        keys.append(extracted)
    return keys
