"""Cobalt client: routing + response shapes (offline, faked HTTP)."""

import asyncio
from pathlib import Path

import pytest

from src.cobalt import CobaltClient, is_cobalt_url
from src.config import Settings
from src.downloader import MediaError


def test_cobalt_hosts():
    assert is_cobalt_url("https://www.instagram.com/reel/abc/")
    assert is_cobalt_url("https://www.tiktok.com/@x/video/1")
    assert is_cobalt_url("https://x.com/user/status/1")
    assert is_cobalt_url("https://m.facebook.com/watch/?v=1")
    assert is_cobalt_url("https://pin.it/abc")
    # YouTube and lookalikes stay with yt-dlp
    assert not is_cobalt_url("https://www.youtube.com/watch?v=1")
    assert not is_cobalt_url("https://youtu.be/abc")
    assert not is_cobalt_url("https://notinstagram.com.evil.com/x")
    assert not is_cobalt_url("https://example.com/video")


def _fake_download_factory(ext: str):
    async def fake_download(file_url, dest_base, *, proxies):
        dest = dest_base.with_suffix(ext)
        dest.write_bytes(b"fake-media")
        return dest
    return fake_download


def test_fetch_tunnel_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = CobaltClient(Settings())

    async def fake_post(url, *, quality, proxies):
        assert quality == "720"
        return {"status": "tunnel", "url": "https://cdn.example/x",
                "filename": "tiktok_cool_dance.mp4"}

    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "_download_one", _fake_download_factory(".mp4"))

    files = asyncio.run(client.fetch("https://www.tiktok.com/@x/video/1", tmp_path))
    assert len(files) == 1
    assert files[0].kind == "video"
    assert files[0].path.is_file()
    assert "cool" in files[0].title.lower()


def test_fetch_picker_album(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = CobaltClient(Settings())

    async def fake_post(url, *, quality, proxies):
        return {"status": "picker", "picker": [
            {"type": "photo", "url": "https://cdn.example/1"},
            {"type": "video", "url": "https://cdn.example/2"},
            {"type": "photo", "url": "https://cdn.example/3"},
        ]}

    async def fake_download(file_url, dest_base, *, proxies):
        ext = ".jpg" if file_url.endswith(("1", "3")) else ".mp4"
        dest = dest_base.with_suffix(ext)
        dest.write_bytes(b"fake")
        return dest

    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "_download_one", fake_download)

    files = asyncio.run(client.fetch("https://www.instagram.com/p/abc/", tmp_path))
    assert [f.kind for f in files] == ["photo", "video", "photo"]


def test_fetch_error_raises_media_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = CobaltClient(Settings())

    async def fake_post(url, *, quality, proxies):
        return {"status": "error", "error": {"code": "error.api.fetch.empty"}}

    monkeypatch.setattr(client, "_post", fake_post)
    with pytest.raises(MediaError):
        asyncio.run(client.fetch("https://www.instagram.com/p/x/", tmp_path))
