import asyncio
from pathlib import Path

from src.cache import (
    audio_key,
    canonicalize_url,
    extractor_key,
    normalize_url,
    video_key,
)
from src.db import Database

YT = "youtube:dQw4w9WgXcQ"


def test_youtube_spellings_collapse():
    for url in (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=trackingjunk",
        "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=x",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?t=42&v=dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    ):
        assert canonicalize_url(url) == YT, url


def test_social_spellings_collapse():
    assert canonicalize_url("https://www.instagram.com/reel/C8abc123-_/?igsh=zzz") == "instagram:C8abc123-_"
    assert canonicalize_url("https://www.tiktok.com/@user/video/7312345678901234567?is_from_webapp=1") == "tiktok:7312345678901234567"
    assert canonicalize_url("https://x.com/someone/status/1801234567890?s=46") == "twitter:1801234567890"
    assert canonicalize_url("https://twitter.com/someone/status/1801234567890") == "twitter:1801234567890"
    assert canonicalize_url("https://www.pinterest.com/pin/123456789012345678/") == "pinterest:123456789012345678"
    assert canonicalize_url("https://soundcloud.com/artist/track-name?si=x") == "soundcloud:artist/track-name"


def test_short_links_normalise():
    a = canonicalize_url("https://vm.tiktok.com/ZMhAbCdEf/?utm_source=share")
    assert a.startswith("url:https://vm.tiktok.com/")
    assert "utm" not in a


def test_normalize_url_strips_tracking_and_sorts():
    out = normalize_url("HTTP://www.Example.com/watch/?b=2&utm_medium=x&a=1#frag")
    assert out == "https://example.com/watch?a=1&b=2"


def test_keys_and_extractor_alias():
    assert audio_key(YT) == f"{YT}|audio"
    assert video_key(YT, "720") == f"{YT}|video|720"
    assert extractor_key("Youtube", "dQw4w9WgXcQ") == YT
    assert extractor_key("TikTok", "123") == "tiktok:123"


def test_db_cache_roundtrip(tmp_path: Path):
    async def scenario():
        db = Database(tmp_path / "t.db")
        await db.open()
        try:
            await body(db)
        finally:
            await db.close()

    async def body(db):
        await db.cache_put("youtube:x|audio", "FILEID1", "audio", "Song", "Artist", 180)
        hit = await db.cache_get("youtube:x|audio")
        assert hit and hit["file_id"] == "FILEID1"
        hit2 = await db.cache_get("youtube:x|audio")
        assert hit2 and hit2["hits"] >= 1  # hit counter grows

        await db.album_put("instagram:abc", [{"kind": "photo", "file_id": "P1"},
                                              {"kind": "video", "file_id": "V1"}], "post")
        items = await db.album_get("instagram:abc")
        assert items and [i["file_id"] for i in items] == ["P1", "V1"]

        await db.index_put("instagram:abc", "album")
        assert await db.index_get("instagram:abc") == "album"

        await db.recognition_put("uniq1", title="T", artist="A")
        rec = await db.recognition_get("uniq1")
        assert rec and rec["title"] == "T"

        stats = await db.cache_stats()
        assert stats["files"] == 1 and stats["albums"] == 1 and stats["hits"] >= 3

        removed = await db.cache_clear()
        assert removed >= 3
        assert await db.cache_get("youtube:x|audio") is None
        await db.close()

    asyncio.run(scenario())
