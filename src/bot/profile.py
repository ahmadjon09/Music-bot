"""Bot identity, auto-applied through the Telegram Bot API.

On every startup (and on demand from the Admin Mini App's *Reset* button)
the bot sets, per language (default + uz/ru/en):

  * ``setMyName``             — display name           (max 64 chars)
  * ``setMyDescription``      — "What can this bot do?" (max 512 chars)
  * ``setMyShortDescription`` — profile/share blurb     (max 120 chars)
  * ``setMyCommands``         — the "/" command menu

So the bot brands itself correctly on a fresh deploy with zero manual
BotFather trips. Language codes are ISO 639-1, per Telegram's spec:
https://core.telegram.org/bots/api#setmyname
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import BotCommand

log = logging.getLogger("musicbot.profile")

# Telegram hard limits — the tests keep our texts honest.
NAME_LIMIT, DESCRIPTION_LIMIT, SHORT_LIMIT = 64, 512, 120

BOT_NAME = "Music Finder"

_SHORT: dict[str, str] = {
    "en": "Download music & videos from YouTube, TikTok, Instagram and 1000+ sites. Search songs, recognize tracks 🎧",
    "uz": "YouTube, TikTok, Instagram va 1000+ saytdan musiqa va video yuklang. Qo'shiq qidiring, trekni aniqlang 🎧",
    "ru": "Скачивайте музыку и видео с YouTube, TikTok, Instagram и 1000+ сайтов. Поиск песен и распознавание треков 🎧",
}

_DESCRIPTION: dict[str, str] = {
    "en": (
        "🎧 Music Finder downloads media and finds songs for you.\n\n"
        "🔗 Send a link — YouTube, TikTok, Instagram, X, Pinterest & 1000+ sites\n"
        "🔍 Send a song name — YouTube search, tap a number, get the MP3\n"
        "🎬 Send a video — I'll name the background track (Shazam)\n\n"
        "⚡️ Cached instant delivery, clean titles, proper cover art.\n"
        "Press START and send your first link!"
    ),
    "uz": (
        "🎧 Music Finder — media yuklab beradi va qoʻshiqlarni topadi.\n\n"
        "🔗 Havola yuboring — YouTube, TikTok, Instagram, X, Pinterest va 1000+ sayt\n"
        "🔍 Qoʻshiq nomini yozing — YouTube’dan topaman, raqamni bossangiz MP3 keladi\n"
        "🎬 Video yuboring — fonidagi trekni aniqlayman (Shazam)\n\n"
        "⚡️ Tezkor kesh, toza sarlavhalar, sifatli muqovalar.\n"
        "START bosing va birinchi havolangizni yuboring!"
    ),
    "ru": (
        "🎧 Music Finder скачивает медиа и находит песни за секунды.\n\n"
        "🔗 Отправьте ссылку — YouTube, TikTok, Instagram, X, Pinterest и 1000+ сайтов\n"
        "🔍 Напишите название песни — найду на YouTube, нажмите номер и получите MP3\n"
        "🎬 Отправьте видео — распознаю фоновый трек (Shazam)\n\n"
        "⚡️ Мгновенная доставка из кэша, чистые названия, обложки.\n"
        "Нажмите START и отправьте первую ссылку!"
    ),
}

COMMANDS: dict[str | None, list[tuple[str, str]]] = {
    None: [  # default (English)
        ("start", "Start the bot"),
        ("audio", "Download MP3 from a link"),
        ("video", "Download video from a link"),
        ("search", "Search a song on YouTube"),
        ("shazam", "Identify music (reply to a video)"),
        ("settings", "Language & quality settings"),
        ("cookies", "Manage your cookies"),
        ("status", "Bot status"),
        ("help", "Help"),
    ],
    "en": [],  # filled from None below — English users get an explicit set too
    "uz": [
        ("start", "Botni boshlash"),
        ("audio", "Havoladan MP3 yuklash"),
        ("video", "Havoladan video yuklash"),
        ("search", "YouTube'da qo'shiq qidirish"),
        ("shazam", "Videodagi musiqani aniqlash"),
        ("settings", "Til va sifat sozlamalari"),
        ("cookies", "Cookies boshqaruvi"),
        ("status", "Bot holati"),
        ("help", "Yordam"),
    ],
    "ru": [
        ("start", "Запустить бота"),
        ("audio", "Скачать MP3 по ссылке"),
        ("video", "Скачать видео по ссылке"),
        ("search", "Найти песню на YouTube"),
        ("shazam", "Распознать музыку в видео"),
        ("settings", "Язык и качество"),
        ("cookies", "Управление cookies"),
        ("status", "Статус бота"),
        ("help", "Помощь"),
    ],
}
COMMANDS["en"] = COMMANDS[None]

#: Languages we brand explicitly (None = Telegram default bucket).
_PROFILE_LANGS: tuple[str | None, ...] = (None, "en", "uz", "ru")


def profile_texts(lang: str | None) -> dict[str, str]:
    key = lang or "en"
    return {
        "name": BOT_NAME,
        "short_description": _SHORT[key],
        "description": _DESCRIPTION[key],
    }


async def _safe(awaitable: Any) -> bool:
    try:
        await awaitable
        return True
    except Exception:  # noqa: BLE001 — one rejected locale must not block the rest
        log.debug("profile call failed", exc_info=True)
        return False


async def apply_bot_profile(bot: Bot) -> dict:
    """Set name, descriptions and commands for every language. Idempotent."""
    report: dict[str, dict[str, bool]] = {}
    for lang in _PROFILE_LANGS:
        code = lang or ""
        texts = profile_texts(lang)
        commands = [BotCommand(command=name, description=desc)
                    for name, desc in COMMANDS[lang]]
        report[lang or "default"] = {
            "name": await _safe(bot.set_my_name(name=texts["name"][:NAME_LIMIT], language_code=code)),
            "description": await _safe(bot.set_my_description(
                description=texts["description"][:DESCRIPTION_LIMIT], language_code=code)),
            "short_description": await _safe(bot.set_my_short_description(
                short_description=texts["short_description"][:SHORT_LIMIT], language_code=code)),
            "commands": await _safe(bot.set_my_commands(commands, language_code=code)),
        }
    ok = sum(v for lang_report in report.values() for v in lang_report.values())
    log.info("bot profile applied: %d/%d calls succeeded", ok, len(_PROFILE_LANGS) * 4)
    return report


async def reset_bot_profile(bot: Bot) -> dict:
    """Wipe every localized name/description/commands, then re-apply fresh.

    This is what the Admin panel's Reset button does — a clean slate for the
    bot's public face, rebuilt from this file in the same breath.
    """
    cleared: dict[str, dict[str, bool]] = {}
    for lang in _PROFILE_LANGS:
        code = lang or ""
        cleared[lang or "default"] = {
            "name": await _safe(bot.set_my_name(name="", language_code=code)),
            "description": await _safe(bot.set_my_description(description="", language_code=code)),
            "short_description": await _safe(
                bot.set_my_short_description(short_description="", language_code=code)),
            "commands": await _safe(bot.delete_my_commands(language_code=code)),
        }
    applied = await apply_bot_profile(bot)
    return {"cleared": cleared, "applied": applied}


async def get_bot_profile(bot: Bot) -> dict:
    """Current live profile per language (for the Admin panel preview)."""
    out: dict[str, dict[str, Any]] = {}
    for lang in _PROFILE_LANGS:
        code = lang or ""
        entry: dict[str, Any] = {}
        try:
            entry["name"] = (await bot.get_my_name(language_code=code)).name
        except Exception:  # noqa: BLE001
            entry["name"] = ""
        try:
            entry["description"] = (await bot.get_my_description(language_code=code)).description
        except Exception:  # noqa: BLE001
            entry["description"] = ""
        try:
            entry["short_description"] = (
                await bot.get_my_short_description(language_code=code)).short_description
        except Exception:  # noqa: BLE001
            entry["short_description"] = ""
        try:
            cmds = await bot.get_my_commands(language_code=code)
            entry["commands"] = [f"/{c.command}" for c in cmds]
        except Exception:  # noqa: BLE001
            entry["commands"] = []
        out[lang or "default"] = entry
    return out
