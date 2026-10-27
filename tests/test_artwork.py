"""Artist portrait provider selection (offline)."""

from src.artwork import _artist_image_url


def test_artist_portrait_prefers_a_close_name_match():
    payload = {
        "data": [
            {"name": "Miyagi Style", "picture_xl": "https://cdn-images.dzcdn.net/images/artist/wrong.jpg"},
            {"name": "Miyagi", "picture_big": "https://cdn-images.dzcdn.net/images/artist/right.jpg"},
        ]
    }
    assert _artist_image_url("Miyagi", payload) == \
        "https://cdn-images.dzcdn.net/images/artist/right.jpg"


def test_artist_portrait_rejects_unrelated_or_untrusted_images():
    unrelated = {"data": [{"name": "Completely Different", "picture_xl":
                            "https://cdn-images.dzcdn.net/images/artist/wrong.jpg"}]}
    untrusted = {"data": [{"name": "Miyagi", "picture_xl": "https://evil.example/image.jpg"}]}
    short_fuzzy = {"data": [{"name": "ABBA", "picture_xl":
                             "https://cdn-images.dzcdn.net/images/artist/wrong.jpg"}]}
    assert _artist_image_url("Miyagi", unrelated) is None
    assert _artist_image_url("Miyagi", untrusted) is None
    assert _artist_image_url("AB", short_fuzzy) is None
