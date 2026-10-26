"""InnerTube fast search: parsing + cache/fallback behaviour (offline)."""

import asyncio

from src.config import Settings
from src.downloader import (
    Downloader,
    MediaError,
    SearchResult,
    _find_continuation,
    _parse_length_text,
    _parse_search_response,
)


def test_parse_length_text():
    assert _parse_length_text("3:47") == 227
    assert _parse_length_text("1:02:33") == 3753
    assert _parse_length_text("0:30") == 30
    assert _parse_length_text("LIVE") == 0
    assert _parse_length_text("") == 0


def _response() -> dict:
    return {
        "contents": {"sectionListRenderer": {"contents": [
            {"itemSectionRenderer": {"contents": [
                {"compactVideoRenderer": {
                    "videoId": "song111aaaa",
                    "title": {"simpleText": "Cool Song (Official Music Video)"},
                    "longBylineText": {"runs": [{"text": "Cool Artist"}]},
                    "lengthText": {"simpleText": "3:47"},
                    "thumbnail": {"thumbnails": [{"url": "https://img/small.jpg"},
                                                 {"url": "https://img/large.jpg"}]},
                }},
                {"videoRenderer": {
                    "videoId": "long222bbbb",
                    "title": {"runs": [{"text": "Epic "}, {"text": "Compilation"}]},
                    "ownerText": {"runs": [{"text": "Some Channel"}]},
                    "lengthText": {"simpleText": "12:00"},  # > 600 s → filtered
                }},
                {"compactVideoRenderer": {
                    "videoId": "live333cccc",
                    "title": {"simpleText": "Live radio 24/7"},
                    "longBylineText": {"runs": [{"text": "Radio"}]},
                    # no lengthText → live → filtered
                }},
                {"compactVideoRenderer": {  # duplicate of the first hit
                    "videoId": "song111aaaa",
                    "title": {"simpleText": "Cool Song"},
                    "lengthText": {"simpleText": "3:47"},
                }},
                {"continuationItemRenderer": {
                    "continuationEndpoint": {"continuationCommand": {"token": "TOK_NEXT"}},
                }},
            ]}},
        ]}},
    }


def test_parse_search_response_filters_and_dedupes():
    results, token = _parse_search_response(_response(), 600)
    assert token == "TOK_NEXT"
    assert len(results) == 1
    hit = results[0]
    assert hit.id == "song111aaaa"
    assert hit.duration == 227
    assert hit.uploader == "Cool Artist"
    assert hit.url == "https://www.youtube.com/watch?v=song111aaaa"
    assert hit.thumbnail == "https://img/large.jpg"


def test_find_continuation_absent():
    assert _find_continuation({"contents": []}) is None


def test_search_falls_back_and_caches(monkeypatch):
    downloader = Downloader(Settings())
    calls = {"ytdlp": 0}

    async def fake_innertube(query, attempts):
        raise MediaError("innertube down")

    async def fake_ytdlp(query, *, cookiefile, attempts):
        calls["ytdlp"] += 1
        return [SearchResult(id="x1", title="Song", uploader="Artist",
                             duration=200, url="https://youtube.com/watch?v=x1")]

    monkeypatch.setattr(downloader, "_innertube_search", fake_innertube)
    monkeypatch.setattr(downloader, "_search_via_ytdlp", fake_ytdlp)

    async def scenario():
        first = await downloader.search("Cool Song")
        second = await downloader.search(" cool   song ")  # same normalised key
        assert first == second and len(first) == 1

    asyncio.run(scenario())
    assert calls["ytdlp"] == 1  # second call came from the cache
