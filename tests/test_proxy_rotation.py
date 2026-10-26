"""Downloader rotates proxies on network-ish failures (faked yt-dlp)."""

import asyncio
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

import src.downloader as dl_module
from src.config import Settings
from src.downloader import Downloader


def test_rotates_to_next_proxy_after_connect_failure(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch):
    media = tmp_path / "song.m4a"
    media.write_bytes(b"fake-audio")
    calls: list[str | None] = []

    class FakeYDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            proxy = self.params.get("proxy")
            calls.append(proxy)
            if proxy and proxy.endswith(":1111"):
                raise DownloadError("Unable to connect to proxy")
            return {
                "id": "x", "title": "A - B", "ext": "m4a", "duration": 10,
                "formats": [{"url": "https://cdn/x", "ext": "m4a"}],
                "requested_downloads": [{"filepath": str(media)}],
            }

    monkeypatch.setattr(dl_module.yt_dlp, "YoutubeDL", FakeYDL)
    downloader = Downloader(Settings())
    reports: list[tuple[str | None, bool]] = []
    downloader.proxy_reporter = lambda url, ok: reports.append((url, ok))

    async def scenario():
        result = await downloader.download_audio(
            "https://www.youtube.com/watch?v=x", tmp_path,
            proxy=["http://1.1.1.1:1111", "http://2.2.2.2:2222"])
        assert result.path == media

    asyncio.run(scenario())
    # dead proxy burned through all 3 client variants, good one worked at once
    assert calls == ["http://1.1.1.1:1111"] * 3 + ["http://2.2.2.2:2222"]
    assert reports.count(("http://1.1.1.1:1111", False)) == 3
    assert reports[-1] == ("http://2.2.2.2:2222", True)


def test_single_string_proxy_still_accepted(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch):
    media = tmp_path / "song.m4a"
    media.write_bytes(b"fake-audio")

    class FakeYDL:
        def __init__(self, params):
            assert params.get("proxy") == "http://3.3.3.3:3333"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return {
                "id": "x", "title": "A - B", "ext": "m4a", "duration": 10,
                "formats": [{"url": "https://cdn/x", "ext": "m4a"}],
                "requested_downloads": [{"filepath": str(media)}],
            }

    monkeypatch.setattr(dl_module.yt_dlp, "YoutubeDL", FakeYDL)
    downloader = Downloader(Settings())

    async def scenario():
        result = await downloader.download_audio(
            "https://example.com/song", tmp_path, proxy="http://3.3.3.3:3333")
        assert result.path == media

    asyncio.run(scenario())
