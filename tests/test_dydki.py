"""Dydki result-card parsing and query caching (offline)."""

import asyncio

from src.config import Settings
from src.dydki import (
    DydkiClient,
    _duration_seconds,
    _valid_mp3_url,
    parse_search_results,
)


def _card(*, title="Song", artist="Artist", duration="3:41", stream=None, song_id="123"):
    stream = stream or f"https://mp3vk.sunproxy.net/file/{song_id}/{title.replace(' ', '_')}.mp3"
    return f"""
    <div class="chkd" data-mp3="{stream}">
      <a class="track__artist" href="/artist/1-artist/"><b>{artist}</b></a>
      <a class="track__title" href="/song/artist-{title.replace(' ', '_')}-{song_id}/">{title}</a>
      <span class="dur">{duration}</span>
    </div>
    """


def test_parse_dydki_cards_extracts_ready_stream_metadata():
    html = "<div class='results'>" + _card(
        title="Косандра &amp; Remix", artist="Miyagi &amp; Andy Panda", song_id="050481986018"
    ) + "</div>"
    results = parse_search_results(html)

    assert len(results) == 1
    result = results[0]
    assert result.source == "dydki"
    assert result.id == "050481986018"
    assert result.title == "Косандра & Remix"
    assert result.uploader == "Miyagi & Andy Panda"
    assert result.duration == 221
    assert result.url == "https://mp3vk.sunproxy.net/file/050481986018/Косандра_&_Remix.mp3"
    assert result.page_url == "https://dydki.net/song/artist-Косандра_&_Remix-050481986018/"
    assert result.artist_url == "https://dydki.net/artist/1-artist/"


def test_parse_filters_invalid_long_duplicate_and_non_mp3_streams():
    html = "".join((
        _card(title="Valid", song_id="1"),
        _card(title="Duplicate", song_id="1"),
        _card(title="Long compilation", duration="106:07", song_id="2"),
        _card(title="Bad host", stream="https://example.com/song.mp3", song_id="3"),
        _card(title="Not mp3", stream="https://mp3vk.sunproxy.net/file/4/song.m4a", song_id="4"),
    ))
    results = parse_search_results(html, max_duration=600)
    assert [result.id for result in results] == ["1"]


def test_dydki_duration_and_stream_validation():
    assert _duration_seconds("2:44") == 164
    assert _duration_seconds("1:02:33") == 3753
    assert _duration_seconds("106:07") == 6367
    assert _duration_seconds("LIVE") == 0
    assert _duration_seconds("2:75") == 0

    assert _valid_mp3_url("https://mp3vk.sunproxy.net/file/id/song.mp3")
    assert not _valid_mp3_url("http://mp3vk.sunproxy.net/file/id/song.mp3")
    assert not _valid_mp3_url("https://example.com/song.mp3")
    assert not _valid_mp3_url("https://user@mp3vk.sunproxy.net/file/id/song.mp3")


def test_dydki_search_results_are_cached_by_normalized_query(monkeypatch):
    client = DydkiClient(Settings())
    calls = 0
    document = _card(title="Kosandra", artist="Miyagi", song_id="55")

    async def fake_request(query):
        nonlocal calls
        calls += 1
        assert query == "Miyagi"
        return document

    monkeypatch.setattr(client, "_request_search_page", fake_request)

    async def scenario():
        first = await client.search("Miyagi")
        second = await client.search("  MIYAGI  ")
        assert first == second
        assert len(second) == 1

    asyncio.run(scenario())
    assert calls == 1
