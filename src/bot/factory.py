"""Builds the aiogram Bot + Dispatcher and registers the command menu."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from ..config import Settings
from ..db import Database
from ..downloader import Downloader
from ..runtime import Runtime
from . import handlers

log = logging.getLogger("musicbot.factory")

_COMMANDS: dict[str | None, list[tuple[str, str]]] = {
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


def build_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def build_dispatcher(settings: Settings, db: Database, runtime: Runtime,
                     downloader: Downloader) -> Dispatcher:
    handlers.init_deps(settings, db, runtime, downloader)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)
    return dp


async def register_commands(bot: Bot) -> None:
    """Telegram's '/' menu, localised per interface language where possible."""
    for language_code, items in _COMMANDS.items():
        commands = [BotCommand(command=name, description=desc) for name, desc in items]
        try:
            await bot.set_my_commands(commands, language_code=language_code or "")
        except Exception:  # noqa: BLE001 — unsupported locale etc. shouldn't stop boot
            log.debug("set_my_commands failed for %r", language_code)
    try:
        await bot.delete_webhook(drop_pending_updates=False)  # polling mode, always
    except Exception:  # noqa: BLE001
        pass
