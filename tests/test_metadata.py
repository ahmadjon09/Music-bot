from src.metadata import clean_title, split_artist_title


def test_clean_title_strips_youtube_noise():
    assert clean_title("Song Name (Official Music Video) [4K]") == "Song Name"
    assert clean_title("Track (Official Audio)") == "Track"
    assert clean_title("Hit Song [Official Lyric Video]") == "Hit Song"


def test_clean_title_keeps_meaningful_brackets():
    assert clean_title("Song (Acoustic Version)") == "Song (Acoustic Version)"


def test_split_prefers_structured_fields():
    performer, title = split_artist_title(
        {"track": "God's Plan", "artist": "Drake", "title": "whatever"})
    assert (performer, title) == ("Drake", "God's Plan")


def test_split_artist_dash_title():
    performer, title = split_artist_title(
        {"title": "The Weeknd - Blinding Lights (Official Video)", "uploader": "TheWeekndVEVO"})
    assert performer == "The Weeknd"
    assert title == "Blinding Lights"


def test_split_falls_back_to_uploader():
    performer, title = split_artist_title(
        {"title": "Some Song", "uploader": "Cool Artist - Topic"})
    assert performer == "Cool Artist"
    assert title == "Some Song"
