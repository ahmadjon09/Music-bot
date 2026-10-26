from src.i18n import LANGS, _STRINGS, normalize_lang, t


def test_all_languages_have_identical_keys():
    reference = set(_STRINGS["en"])
    for lang in LANGS:
        assert set(_STRINGS[lang]) == reference, f"{lang} diverges"


def test_format_placeholders_match_across_languages():
    import re

    def placeholders(s: str) -> set[str]:
        return set(re.findall(r"\{(\w+)\}", s))

    for key in _STRINGS["en"]:
        expected = placeholders(_STRINGS["en"][key])
        for lang in LANGS:
            assert placeholders(_STRINGS[lang][key]) == expected, f"{key} in {lang}"


def test_normalize_lang():
    assert normalize_lang("ru-RU") == "ru"
    assert normalize_lang("uz") == "uz"
    assert normalize_lang("de") == "en"
    assert normalize_lang(None) == "uz"


def test_translate_formats():
    out = t("uz", "your_id", id=42)
    assert "42" in out
