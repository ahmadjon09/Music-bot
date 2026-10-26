"""Bot identity: Telegram length limits + apply/reset against a fake Bot."""

import asyncio
import re

from src.bot.profile import (
    COMMANDS,
    DESCRIPTION_LIMIT,
    NAME_LIMIT,
    SHORT_LIMIT,
    apply_bot_profile,
    profile_texts,
    reset_bot_profile,
)


def test_texts_respect_telegram_limits():
    for lang in (None, "en", "uz", "ru"):
        texts = profile_texts(lang)
        assert 0 < len(texts["name"]) <= NAME_LIMIT
        assert len(texts["description"]) <= DESCRIPTION_LIMIT
        assert len(texts["short_description"]) <= SHORT_LIMIT


def test_commands_are_valid_and_uniform():
    names = [c for c, _ in COMMANDS[None]]
    for lang, items in COMMANDS.items():
        assert [c for c, _ in items] == names  # same menu in every language
        for command, description in items:
            assert re.fullmatch(r"[a-z0-9_]{1,32}", command)
            assert 1 <= len(description) <= 256


class FakeBot:
    """Records every Bot API call instead of hitting Telegram."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_my_name(self, name=None, language_code=None):
        self.calls.append(("set_my_name", {"name": name, "language_code": language_code}))
        return True

    async def set_my_description(self, description=None, language_code=None):
        self.calls.append(("set_my_description",
                           {"description": description, "language_code": language_code}))
        return True

    async def set_my_short_description(self, short_description=None, language_code=None):
        self.calls.append(("set_my_short_description",
                           {"short_description": short_description, "language_code": language_code}))
        return True

    async def set_my_commands(self, commands, language_code=None, **kwargs):
        self.calls.append(("set_my_commands",
                           {"n": len(commands), "language_code": language_code}))
        return True

    async def delete_my_commands(self, language_code=None, **kwargs):
        self.calls.append(("delete_my_commands", {"language_code": language_code}))
        return True


def test_apply_covers_every_language():
    bot = FakeBot()
    report = asyncio.run(apply_bot_profile(bot))  # type: ignore[arg-type]
    assert set(report) == {"default", "en", "uz", "ru"}
    assert all(all(fields.values()) for fields in report.values())
    langs = {kwargs["language_code"] for name, kwargs in bot.calls if name == "set_my_name"}
    assert langs == {"", "en", "uz", "ru"}


def test_reset_clears_then_reapplies():
    bot = FakeBot()
    result = asyncio.run(reset_bot_profile(bot))  # type: ignore[arg-type]
    kinds = [name for name, _ in bot.calls]
    assert "cleared" in result and "applied" in result
    # a wipe happens before the final re-apply
    assert kinds.index("delete_my_commands") < len(kinds) - 1 - kinds[::-1].index("set_my_commands")
    # the very last name written per language is the real name, not the empty wipe
    last_names = {}
    for name, kwargs in bot.calls:
        if name == "set_my_name":
            last_names[kwargs["language_code"]] = kwargs["name"]
    assert all(last_names.values())
