from src.bot.state import SearchStore, TokenRegistry, progress_bar
from src.downloader import Downloader
from src.config import Settings


def test_progress_bar_bounds():
    assert progress_bar(0, 10) == "▱" * 10
    assert progress_bar(100, 10) == "▰" * 10
    assert progress_bar(50, 10).count("▰") == 5


def test_token_registry_roundtrip():
    reg = TokenRegistry()
    token = reg.put("https://example.com/video")
    assert reg.get(token) == "https://example.com/video"
    assert reg.get("nope") is None


def test_search_store_roundtrip():
    store = SearchStore()
    token = store.put("query", [])
    assert store.get(token) == ("query", [])
    assert store.get("missing") is None


def test_search_filtering_logic_via_fake_info():
    """_to_media_info should spot video formats and image-only posts."""
    dl = Downloader(Settings())
    video = dl._to_media_info({
        "id": "1", "title": "A - B", "ext": "mp4",
        "formats": [{"vcodec": "avc1", "ext": "mp4"}],
    })
    assert video.has_video and not video.is_image

    image = dl._to_media_info({
        "id": "2", "title": "pic", "ext": "jpg",
        "formats": [{"vcodec": "none", "ext": "jpg"}],
    })
    assert image.is_image

    carousel = dl._to_media_info({
        "id": "3", "title": "post", "_type": "playlist",
        "entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
    })
    assert carousel.is_carousel and len(carousel.entries) == 3
