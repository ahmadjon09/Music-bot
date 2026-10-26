"""Builds the aiogram Bot + Dispatcher and registers the command menu."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ..config import Settings
from ..db import Database
from ..downloader import Downloader
from ..runtime import Runtime
from . import handlers
from .profile import apply_bot_profile

log = logging.getLogger("musicbot.factory")

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
    """Auto-brand the bot at boot: name, descriptions, "/" menu (uz/ru/en)."""
    await apply_bot_profile(bot)
    try:
        await bot.delete_webhook(drop_pending_updates=False)  # polling mode, always
    except Exception:  # noqa: BLE001
        pass
