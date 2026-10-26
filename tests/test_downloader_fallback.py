"""YouTube client fallbacks + error classification (offline, faked yt-dlp)."""

import asyncio
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from src.config import Settings
from src.downloader import (
    BotCheckError,
    Downloader,
    FormatUnavailableError,
    _client_variants,
    _is_youtube_url,
    classify_error,
)


def test_classify_botcheck_and_format():
    bot = classify_error(DownloadError("Sign in to confirm you're not a bot"))
    assert isinstance(bot, BotCheckError) and bot.i18n_key == "error_botcheck"
    fmt = classify_error(DownloadError("Requested format is not available"))
    assert isinstance(fmt, FormatUnavailableError) and fmt.i18n_key == "error_format"


def test_variants_only_for_youtube():
    assert _is_youtube_url("https://youtu.be/abc")
    assert not _is_youtube_url("https://www.tiktok.com/@x/video/1")
    yt = _client_variants("https://www.youtube.com/watch?v=x")
    assert len(yt) == 3 and yt[1][1] is True  # fallback attempts drop cookies
    assert _client_variants("https://example.com/v") == [({}, False)]


def test_download_retries_with_android_vr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    media = tmp_path / "song.m4a"
    media.write_bytes(b"fake-audio")

    class FakeYDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            calls.append(self.params)
            if len(calls) == 1:
                raise DownloadError("ERROR: Requested format is not available")
            return {
                "id": "x", "title": "A - B", "ext": "m4a", "duration": 10,
                "formats": [{"url": "https://cdn/x", "ext": "m4a"}],
                "requested_downloads": [{"filepath": str(media)}],
            }

    import src.downloader as dl_module

    monkeypatch.setattr(dl_module.yt_dlp, "YoutubeDL", FakeYDL)
    downloader = Downloader(Settings())

    async def scenario():
        result = await downloader.download_audio(
            "https://www.youtube.com/watch?v=x", tmp_path,
            cookiefile="/tmp/cookies.txt")
        assert result.path == media

    asyncio.run(scenario())
    assert len(calls) == 2
    assert calls[0].get("cookiefile") == "/tmp/cookies.txt"
    # second attempt: android_vr client, cookies dropped
    assert calls[1].get("extractor_args") == {"youtube": {"player_client": ["android_vr"]}}
    assert "cookiefile" not in calls[1]
    # audio selector is format-permissive, not mp3-only
    fmt = calls[0]["format"]
    assert "ba[ext=m4a]" in fmt and "ba[ext=mp3]" in fmt and fmt.rstrip().endswith("/best")
