"""Inline keyboards. All navigation edits ONE message — no chat spam."""

from __future__ import annotations

import math

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..downloader import SearchResult
from ..i18n import LANGS, t

QUALITIES = ("best", "1080", "720", "480", "360")


def main_menu(lang: str, *, is_admin: bool = False, webapp_url: str = "") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_help"), callback_data="nav:help")
    kb.button(text=t(lang, "btn_settings"), callback_data="nav:settings")
    kb.button(text=t(lang, "btn_status"), callback_data="nav:status")
    kb.adjust(2, 1)
    if is_admin and webapp_url:  # the Mini App button exists for admins ONLY
        kb.row(InlineKeyboardButton(text=t(lang, "btn_admin"),
                                    web_app=WebAppInfo(url=webapp_url)))
    return kb.as_markup()


def back_button(lang: str, target: str = "nav:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_back"), callback_data=target)
    return kb.as_markup()


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_language"), callback_data="nav:lang")
    kb.button(text=t(lang, "btn_quality"), callback_data="nav:quality")
    kb.button(text=t(lang, "btn_back"), callback_data="nav:home")
    kb.adjust(2, 1)
    return kb.as_markup()


def language_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, label in LANGS.items():
        kb.button(text=label, callback_data=f"lang:{code}")
    kb.adjust(3)
    return kb.as_markup()


def quality_kb(lang: str, current: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for q in QUALITIES:
        mark = "✅ " if q == current else ""
        label = f"{mark}{q}p" if q.isdigit() else f"{mark}Best"
        kb.button(text=label, callback_data=f"quality:{q}")
    kb.adjust(5)
    kb.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="nav:settings"))
    return kb.as_markup()


def admin_button(lang: str, webapp_url: str) -> InlineKeyboardMarkup | None:
    if not webapp_url:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_admin"), web_app=WebAppInfo(url=webapp_url))
    return kb.as_markup()


def search_page_kb(lang: str, token: str, page: int, results: list[SearchResult],
                   page_size: int = 10) -> InlineKeyboardMarkup:
    """Numbered pick-buttons (2×5) + pagination row — the heart of search UX."""
    total_pages = max(1, math.ceil(len(results) / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    page_items = results[start:start + page_size]

    kb = InlineKeyboardBuilder()
    for offset, _item in enumerate(page_items):
        idx = start + offset
        kb.button(text=str(idx + 1), callback_data=f"pick:{token}:{idx}")
    kb.adjust(5, 5)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=t(lang, "page_prev"),
                                        callback_data=f"page:{token}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text=t(lang, "page_next"),
                                        callback_data=f"page:{token}:{page + 1}"))
    kb.row(*nav)
    kb.row(InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:close"))
    return kb.as_markup()


def delivered_video_kb(lang: str, url_token: str) -> InlineKeyboardMarkup:
    """Under every delivered video: one tap turns it into an MP3."""
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_mp3"), callback_data=f"mp3:{url_token}")
    return kb.as_markup()


def incoming_video_kb(lang: str, token: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_shazam"), callback_data=f"shazam:{token}")
    kb.button(text=t(lang, "btn_audio_from_video"), callback_data=f"vaudio:{token}")
    kb.adjust(1, 1)
    return kb.as_markup()


def recognized_kb(lang: str, token: str, shazam_url: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_mp3"), callback_data=f"recmp3:{token}")
    kb.button(text=t(lang, "btn_search_youtube"), callback_data=f"recsearch:{token}")
    if shazam_url:
        kb.button(text="🔗 Shazam", url=shazam_url)
    kb.adjust(2, 1)
    return kb.as_markup()


def cookies_kb(lang: str, has_cookies: bool) -> InlineKeyboardMarkup | None:
    if not has_cookies:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_delete_cookies"), callback_data="cookies:delete")
    return kb.as_markup()
