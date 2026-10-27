from src.metadata import (
    clean_title,
    media_filename,
    prepare_telegram_thumbnail,
    split_artist_title,
)


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


def test_clean_title_strips_unbracketed_tails():
    assert clean_title("The Weeknd - Blinding Lights Official Music Video") == "The Weeknd - Blinding Lights"
    assert clean_title("Song (Official Video) HD") == "Song"
    assert clean_title("Song (Official MV) 4K") == "Song"
    assert clean_title("Qoshiq Music Video") == "Qoshiq"
    assert clean_title("Video") == "Video"  # a real one-word title survives


def test_clean_title_strips_premiere_shouts():
    assert clean_title("Премьера клипа! Artist - Song") == "Artist - Song"
    assert clean_title("Artist - Track [Премьера клипа, 2024]") == "Artist - Track"


def test_telegram_thumbnail_obeys_bot_api_limits():
    import io

    from PIL import Image

    source = io.BytesIO()
    Image.new("RGB", (1200, 800), "navy").save(source, format="PNG")
    thumbnail = prepare_telegram_thumbnail(source.getvalue(), square=True)
    assert thumbnail and len(thumbnail) <= 200_000
    image = Image.open(io.BytesIO(thumbnail))
    assert image.format == "JPEG"
    assert image.size == (320, 320)


def test_media_filename_is_human_friendly():
    assert media_filename("Never Gonna Give You Up", "Rick Astley", "m4a") == "Rick Astley - Never Gonna Give You Up.m4a"
    assert media_filename("Song: Part 2?", "A/B", ".MP3") == "A B - Song Part 2.mp3"
    assert media_filename("Solo", "Unknown artist", "webm") == "Solo.webm"
