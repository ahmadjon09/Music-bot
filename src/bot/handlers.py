"""All bot handlers — commands, links, text search, recognition, callbacks.

UX rule of the house: ONE status message per job, edited in place with an
animated progress bar, then deleted when the media lands. Clean chats only.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import math
import re
import shutil
import tempfile
from pathlib import Path

import aiohttp
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from .. import __version__, security
from ..cache import (all_keys, audio_key, canonicalize_url, extractor_key,
                     photo_key, upload_audio_key, video_key)
from ..config import Settings
from ..db import Database
from ..downloader import Downloader, MediaError, Progress, ytdlp_version
from ..gallery import fetch_gallery
from ..i18n import LANGS, normalize_lang, t
from ..metadata import audio_duration, fmt_duration, prepare_cover, tag_audio
from ..proxy import ProxyParseError
from ..recognize import RecognizedTrack, recognize_file
from ..runtime import Runtime
from . import keyboards as kb
from .state import DownloadGate, SearchStore, TokenRegistry, progress_bar, spinner_frame, uptime_text

log = logging.getLogger("musicbot.handlers")

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
router = Router(name="main")

# ── wiring (filled by factory.build_dispatcher) ──────────────────────────────
class Deps:
    settings: Settings
    db: Database
    runtime: Runtime
    downloader: Downloader
    gate: DownloadGate
    searches = SearchStore()
    tokens = TokenRegistry()


def init_deps(settings: Settings, db: Database, runtime: Runtime, downloader: Downloader) -> None:
    Deps.settings, Deps.db, Deps.runtime, Deps.downloader = settings, db, runtime, downloader
    Deps.gate = DownloadGate(settings.max_global_downloads, settings.max_user_downloads)


# ── small helpers ────────────────────────────────────────────────────────────
def _esc(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


async def _lang(message_or_user_id: int, telegram_lang: str | None = None) -> tuple[str, dict]:
    user = await Deps.db.upsert_user(message_or_user_id, normalize_lang(telegram_lang))
    return user.get("lang", "uz"), user


def _webapp_url() -> str:
    base = Deps.settings.public_base_url
    return f"{base}/admin" if base else ""


def _find_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(").,") if match else None


async def _maintenance_block(message: Message, lang: str) -> bool:
    if Deps.runtime.maintenance and not Deps.settings.is_admin(message.from_user.id if message.from_user else None):
        await message.answer(t(lang, "maintenance_on"))
        return True
    return False


class StatusMessage:
    """The single editable progress message for one job."""

    def __init__(self, message: Message, lang: str) -> None:
        self._msg = message
        self._lang = lang
        self._last_text = ""

    async def set(self, key: str, **kwargs: object) -> None:
        text = t(self._lang, key, spinner=spinner_frame(), **kwargs)
        if text == self._last_text:
            return
        self._last_text = text
        with contextlib.suppress(Exception):
            await self._msg.edit_text(text)

    async def progress(self, p: Progress) -> None:
        if p.percent > 0:
            await self.set("downloading", bar=progress_bar(p.percent),
                           perc=f"{p.percent:.0f}", speed=p.speed, eta=p.eta)
        else:
            await self.set("downloading_simple")

    async def delete(self) -> None:
        with contextlib.suppress(Exception):
            await self._msg.delete()


def _job_dir() -> Path:
    return Path(tempfile.mkdtemp(dir=Deps.settings.tmp_dir, prefix="job_"))


async def _fetch_bytes(url: str | None, proxy: str | None = None) -> bytes | None:
    if not url:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:  # noqa: BLE001 — thumbnails are decoration, not cargo
        return None
    return None


async def _thumb_file(url: str | None, job: Path, proxy: str | None) -> FSInputFile | None:
    raw = await _fetch_bytes(url, proxy)
    if not raw:
        return None
    jpeg = await asyncio.to_thread(prepare_cover, raw, square=False, max_size=480)
    if not jpeg:
        return None
    path = job / "thumb.jpg"
    path.write_bytes(jpeg)
    return FSInputFile(str(path))


# ── /start, /help, navigation ────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    text = t(lang, "start_title", name=_esc(message.from_user.first_name)) + "\n\n" + t(lang, "start_body")
    await message.answer(text, reply_markup=kb.main_menu(
        lang, is_admin=Deps.settings.is_admin(message.from_user.id), webapp_url=_webapp_url()))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(t(lang, "help_text"), reply_markup=kb.back_button(lang))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(t(lang, "your_id", id=message.from_user.id))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(await _status_text(lang), reply_markup=kb.back_button(lang))


async def _status_text(lang: str) -> str:
    stats = await Deps.db.stats()
    return t(lang, "status_text", uptime=uptime_text(), users=stats["users"],
             downloads=stats["downloads"], cached=stats["cached"],
             ytdlp=ytdlp_version(), version=__version__)


def _home_text(lang: str, name: str) -> str:
    return t(lang, "start_title", name=_esc(name)) + "\n\n" + t(lang, "start_body")


def _settings_text(lang: str, user: dict) -> str:
    quality = user.get("quality", "720")
    quality_label = f"{quality}p" if str(quality).isdigit() else "Best"
    return (t(lang, "settings_title") + "\n\n"
            + t(lang, "settings_lang", lang=LANGS.get(lang, lang)) + "\n"
            + t(lang, "settings_quality", quality=quality_label))


@router.callback_query(F.data.startswith("nav:"))
async def on_nav(call: CallbackQuery) -> None:
    assert call.from_user and call.message and call.data
    lang, user = await _lang(call.from_user.id, call.from_user.language_code)
    target = call.data.split(":", 1)[1]
    msg = call.message
    assert isinstance(msg, Message)
    if target == "close":
        with contextlib.suppress(Exception):
            await msg.delete()
    elif target == "home":
        await msg.edit_text(_home_text(lang, call.from_user.first_name), reply_markup=kb.main_menu(
            lang, is_admin=Deps.settings.is_admin(call.from_user.id), webapp_url=_webapp_url()))
    elif target == "help":
        await msg.edit_text(t(lang, "help_text"), reply_markup=kb.back_button(lang))
    elif target == "status":
        await msg.edit_text(await _status_text(lang), reply_markup=kb.back_button(lang))
    elif target == "settings":
        await msg.edit_text(_settings_text(lang, user), reply_markup=kb.settings_kb(lang))
    elif target == "lang":
        await msg.edit_text(t(lang, "choose_lang"), reply_markup=kb.language_kb())
    elif target == "quality":
        await msg.edit_text(t(lang, "choose_quality"),
                            reply_markup=kb.quality_kb(lang, user.get("quality", "720")))
    await call.answer()


@router.message(Command("lang", "settings"))
async def cmd_settings(message: Message) -> None:
    assert message.from_user
    lang, user = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(_settings_text(lang, user), reply_markup=kb.settings_kb(lang))


@router.callback_query(F.data.startswith("lang:"))
async def on_lang(call: CallbackQuery) -> None:
    assert call.from_user and call.message and call.data
    new_lang = call.data.split(":", 1)[1]
    if new_lang not in LANGS:
        await call.answer()
        return
    await Deps.db.set_lang(call.from_user.id, new_lang)
    _, user = await _lang(call.from_user.id, new_lang)
    msg = call.message
    assert isinstance(msg, Message)
    await msg.edit_text(_settings_text(new_lang, user), reply_markup=kb.settings_kb(new_lang))
    await call.answer(t(new_lang, "lang_saved"))


@router.callback_query(F.data.startswith("quality:"))
async def on_quality(call: CallbackQuery) -> None:
    assert call.from_user and call.message and call.data
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    quality = call.data.split(":", 1)[1]
    if quality not in kb.QUALITIES:
        await call.answer()
        return
    await Deps.db.set_quality(call.from_user.id, quality)
    _, user = await _lang(call.from_user.id, call.from_user.language_code)
    msg = call.message
    assert isinstance(msg, Message)
    label = f"{quality}p" if quality.isdigit() else "Best"
    await msg.edit_text(_settings_text(lang, user), reply_markup=kb.settings_kb(lang))
    await call.answer(t(lang, "quality_saved", quality=label))


@router.callback_query(F.data == "noop")
async def on_noop(call: CallbackQuery) -> None:
    await call.answer()


# ── admin commands ───────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    if not Deps.settings.is_admin(message.from_user.id):
        await message.answer(t(lang, "admin_only"))
        return
    markup = kb.admin_button(lang, _webapp_url())
    if markup is None:
        await message.answer(t(lang, "admin_no_url"))
        return
    await message.answer(t(lang, "admin_panel_text"), reply_markup=markup)


@router.message(Command("setproxy"))
async def cmd_setproxy(message: Message, command: CommandObject) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    if not Deps.settings.is_admin(message.from_user.id):
        await message.answer(t(lang, "admin_only"))
        return
    raw = (command.args or "").strip()
    try:
        if not raw or raw.lower() in {"off", "none", "clear", "o'chirish"}:
            await Deps.runtime.clear_proxies()
            await message.answer(t(lang, "proxy_cleared"))
        else:
            pool = await Deps.runtime.set_proxies(raw)
            await message.answer(t(lang, "proxy_saved", proxy=", ".join(p.masked for p in pool)))
    except ProxyParseError as exc:
        await message.answer(t(lang, "proxy_invalid", error=_esc(str(exc))))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    if not Deps.settings.is_admin(message.from_user.id):
        await message.answer(t(lang, "admin_only"))
        return
    stats = await Deps.db.stats()
    await message.answer(t(lang, "stats_text", users=stats["users"], downloads=stats["downloads"],
                           cached=stats["cached"], uptime=uptime_text(),
                           proxy=_esc(Deps.runtime.proxy_label())))


# ── cookies (per-user, encrypted) ────────────────────────────────────────────
@router.message(Command("cookies"))
async def cmd_cookies(message: Message) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    has = bool(await Deps.db.get_user_cookies(message.from_user.id))
    status = t(lang, "cookies_status_on" if has else "cookies_status_off")
    await message.answer(t(lang, "cookies_prompt", status=status),
                         reply_markup=kb.cookies_kb(lang, has))


@router.callback_query(F.data == "cookies:delete")
async def on_cookies_delete(call: CallbackQuery) -> None:
    assert call.from_user
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    await Deps.db.delete_user_cookies(call.from_user.id)
    await call.answer(t(lang, "cookies_deleted"), show_alert=True)


@router.message(F.document)
async def on_document(message: Message, bot: Bot) -> None:
    """A document whose name smells like cookies = a cookie upload."""
    assert message.from_user and message.document
    doc = message.document
    name = (doc.file_name or "").lower()
    if "cookie" not in name and not name.endswith(".txt"):
        return
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    if (doc.file_size or 0) > security.MAX_COOKIE_BYTES:
        await message.answer(t(lang, "cookies_invalid", error="> 1 MB"))
        return
    try:
        buf = await bot.download(doc)
        if buf is None:
            raise RuntimeError("empty download")
        content = buf.read().decode(errors="ignore")
    except Exception:  # noqa: BLE001
        await message.answer(t(lang, "error_generic"))
        return
    report = security.validate_cookies(content)
    if not report["ok"]:
        await message.answer(t(lang, "cookies_invalid", error=_esc(report["error"])))
        return
    is_admin = Deps.settings.is_admin(message.from_user.id)
    if is_admin:  # admin uploads become the global jar for everyone
        await Deps.runtime.set_global_cookies(content)
    else:
        blob = security.encrypt_text(Deps.settings.secret_key, content)
        await Deps.db.set_user_cookies(message.from_user.id, blob)
    await message.answer(t(lang, "cookies_saved", total=report["total"],
                           domains=len(report["domains"])))


# ── cache-aware delivery ─────────────────────────────────────────────────────
# Every file we successfully send is remembered by its Telegram file_id.
# The next user asking for the same media — via *any* spelling of the URL —
# gets it re-sent from Telegram's own servers. No download, no disk, ~instant.

def _canonicals_for(canonical: str, info) -> list[str]:
    extracted = extractor_key(info.extractor, info.id) if info and info.id else None
    return all_keys(canonical, extracted)


async def _send_cached_single(message: Message, hit: dict, *, lang: str, url: str) -> None:
    title = _esc(hit.get("title") or "")
    if hit["kind"] == "audio":
        await message.answer_audio(hit["file_id"])
    elif hit["kind"] == "photo":
        caption = (f"🖼 <b>{title}</b>\n" if title else "") + t(lang, "from_cache")
        await message.answer_photo(hit["file_id"], caption=caption)
    else:
        token = Deps.tokens.put(url)
        caption = (f"🎬 <b>{title}</b>\n" if title else "") + t(lang, "from_cache")
        await message.answer_video(hit["file_id"], caption=caption,
                                   reply_markup=kb.delivered_video_kb(lang, token))


async def _send_cached_album(message: Message, items: list[dict], *, lang: str, title: str = "") -> None:
    caption = (t(lang, "carousel_caption", title=_esc(title)) + "\n" if title else "") + t(lang, "from_cache")
    for start in range(0, len(items), 10):
        chunk = items[start:start + 10]
        if len(chunk) == 1:
            item = chunk[0]
            cap = caption if start == 0 else None
            if item.get("kind") == "video":
                await message.answer_video(item["file_id"], caption=cap)
            else:
                await message.answer_photo(item["file_id"], caption=cap)
            continue
        media = []
        for idx, item in enumerate(chunk):
            cap = caption if (start == 0 and idx == 0) else None
            if item.get("kind") == "video":
                media.append(InputMediaVideo(media=item["file_id"], caption=cap))
            else:
                media.append(InputMediaPhoto(media=item["file_id"], caption=cap))
        await message.answer_media_group(media)


async def _try_cache(message: Message, canonicals: list[str], *, lang: str, user: dict,
                     user_id: int, url: str, force: str | None,
                     status: StatusMessage | None = None) -> bool:
    """Serve from the file_id cache when possible. True = delivered, done."""

    async def _serve_file(key_of) -> tuple[str, str] | None:
        for canon in canonicals:
            key = key_of(canon)
            hit = await Deps.db.cache_get(key)
            if not hit:
                continue
            try:
                await _send_cached_single(message, hit, lang=lang, url=url)
                return hit["kind"], hit.get("title") or ""
            except Exception:  # noqa: BLE001 — stale file_id: forget it, re-download
                log.debug("evicting stale cache entry %s", key)
                await Deps.db.cache_delete(key)
        return None

    async def _serve_album() -> tuple[str, str] | None:
        for canon in canonicals:
            items = await Deps.db.album_get(canon)
            if not items:
                continue
            try:
                await _send_cached_album(message, items, lang=lang)
                return "album", ""
            except Exception:  # noqa: BLE001
                await Deps.db.album_delete(canon)
        return None

    quality = str(user.get("quality", "720"))
    served: tuple[str, str] | None = None
    if force == "audio":
        served = await _serve_file(audio_key)
    elif force == "video":
        served = await _serve_file(lambda c: video_key(c, quality))
    else:
        # Default mode must return what the link *is*. The media index knows.
        primary = None
        for canon in canonicals:
            primary = await Deps.db.index_get(canon)
            if primary:
                break
        if primary == "album":
            served = await _serve_album()
        elif primary == "audio":
            served = await _serve_file(audio_key)
        elif primary == "photo":
            served = await _serve_file(photo_key) or await _serve_album()
        elif primary == "video":
            served = await _serve_file(lambda c: video_key(c, quality))
        else:  # unknown link — try the safe kinds (never guess "audio")
            served = await _serve_album() or await _serve_file(lambda c: video_key(c, quality)) \
                or await _serve_file(photo_key)

    if not served:
        return False
    kind, title = served
    if status:
        await status.delete()
    await Deps.db.bump_downloads(user_id)
    await Deps.db.log_download(user_id, url, f"{kind}⚡cache", title)
    return True


async def _remember(canonicals: list[str], primary: str | None) -> None:
    if primary:
        for canon in canonicals:
            await Deps.db.index_put(canon, primary)


async def deliver_audio(message: Message, downloaded, job: Path, *, lang: str,
                        user_id: int, url: str, canonicals: list[str],
                        set_primary: bool, proxy: str | None,
                        status: StatusMessage) -> None:
    await status.set("processing")
    raw_cover = await _fetch_bytes(downloaded.thumbnail_url, proxy)
    cover = await asyncio.to_thread(prepare_cover, raw_cover, square=True, max_size=640) if raw_cover else None
    await asyncio.to_thread(tag_audio, downloaded.path, downloaded.title, downloaded.performer, cover)
    duration = downloaded.duration or await asyncio.to_thread(audio_duration, downloaded.path)
    thumb = None
    if cover:
        thumb_path = job / "cover.jpg"
        thumb_path.write_bytes(cover)
        thumb = FSInputFile(str(thumb_path))
    await status.set("uploading")
    sent = await message.answer_audio(
        FSInputFile(str(downloaded.path)), title=downloaded.title[:64],
        performer=(downloaded.performer or "")[:64] or None,
        duration=duration or None, thumbnail=thumb)
    if sent.audio:  # ⚡️ remember it under every spelling of this media
        for canon in canonicals:
            await Deps.db.cache_put(audio_key(canon), sent.audio.file_id, "audio",
                                    downloaded.title, downloaded.performer, duration)
        await _remember(canonicals, "audio" if set_primary else None)
    await _after_delivery(message, status, user_id, url, "audio", downloaded.title)


async def deliver_video(message: Message, downloaded, job: Path, *, lang: str,
                        user_id: int, url: str, canonicals: list[str], quality: str,
                        set_primary: bool, proxy: str | None,
                        status: StatusMessage) -> None:
    await status.set("uploading")
    thumb = await _thumb_file(downloaded.thumbnail_url, job, proxy)
    token = Deps.tokens.put(url)
    sent = await message.answer_video(
        FSInputFile(str(downloaded.path)), duration=downloaded.duration or None,
        width=downloaded.width or None, height=downloaded.height or None,
        thumbnail=thumb, supports_streaming=True,
        caption=f"🎬 <b>{_esc(downloaded.title)}</b>",
        reply_markup=kb.delivered_video_kb(lang, token))
    if sent.video:
        for canon in canonicals:
            await Deps.db.cache_put(video_key(canon, quality), sent.video.file_id, "video",
                                    downloaded.title, downloaded.performer, downloaded.duration)
        await _remember(canonicals, "video" if set_primary else None)
    await _after_delivery(message, status, user_id, url, "video", downloaded.title)


async def deliver_album(message: Message, files: list, *, lang: str, user_id: int,
                        url: str, title: str, canonicals: list[str],
                        status: StatusMessage) -> None:
    await status.set("uploading")
    caption = t(lang, "carousel_caption", title=_esc(title)) if title else None
    delivered: list[dict] = []  # file_ids of what actually landed, in order
    for start in range(0, len(files), 10):  # Telegram albums: max 10 items
        chunk = files[start:start + 10]
        if len(chunk) == 1:
            item = chunk[0]
            if item.kind == "video":
                sent = await message.answer_video(FSInputFile(str(item.path)), caption=caption)
                if sent.video:
                    delivered.append({"kind": "video", "file_id": sent.video.file_id})
            else:
                sent = await message.answer_photo(FSInputFile(str(item.path)), caption=caption)
                if sent.photo:
                    delivered.append({"kind": "photo", "file_id": sent.photo[-1].file_id})
            continue
        media = []
        for idx, item in enumerate(chunk):
            fs = FSInputFile(str(item.path))
            cap = caption if (start == 0 and idx == 0) else None
            media.append(InputMediaVideo(media=fs, caption=cap) if item.kind == "video"
                         else InputMediaPhoto(media=fs, caption=cap))
        sent_group = await message.answer_media_group(media)
        for sent in sent_group:
            if sent.video:
                delivered.append({"kind": "video", "file_id": sent.video.file_id})
            elif sent.photo:
                delivered.append({"kind": "photo", "file_id": sent.photo[-1].file_id})
    if delivered:  # ⚡️ the whole carousel, cached as one ordered payload
        for canon in canonicals:
            await Deps.db.album_put(canon, delivered, title)
        await _remember(canonicals, "album")
    await _after_delivery(message, status, user_id, url, "album", title)


async def _after_delivery(message: Message, status: StatusMessage, user_id: int,
                          url: str, kind: str, title: str) -> None:
    await status.delete()
    await Deps.db.bump_downloads(user_id)
    await Deps.db.log_download(user_id, url, kind, title)


# ── the main pipeline: one URL in, media out ─────────────────────────────────
async def process_url(message: Message, url: str, *, lang: str, user: dict,
                      force: str | None = None, origin: Message | None = None,
                      actor_id: int | None = None) -> None:
    """force: 'audio' | 'video' | None (None = original media, the default).

    Pipeline: canonicalise → ⚡ cache (pre-network!) → busy gate → extract →
    ⚡ cache again under the resolved id (short links) → download → deliver →
    remember everything for the next user.
    """
    assert message.from_user
    user_id = actor_id or message.from_user.id
    canonical = canonicalize_url(url)

    # ⚡️ Fastest path in the building: no queue, no gate, no yt-dlp at all.
    if await _try_cache(message, [canonical], lang=lang, user=user,
                        user_id=user_id, url=url, force=force):
        return

    if Deps.gate.user_busy(user_id):
        await message.answer(t(lang, "busy_user"))
        return
    status_msg = origin or await message.answer(t(lang, "queue_wait"))
    status = StatusMessage(status_msg, lang)
    job: Path | None = None
    try:
        async with Deps.gate.slot(user_id):
            job = _job_dir()
            async with Deps.runtime.ytdlp_context(user_id) as (cookiefile, proxy):
                await status.set("analyzing")
                info = None
                try:
                    info = await Deps.downloader.extract(url, cookiefile=cookiefile, proxy=proxy)
                except MediaError:
                    if force:  # honour explicit /audio even when probing failed
                        raise
                    info = None  # → gallery-dl gets a shot below

                canonicals = _canonicals_for(canonical, info)
                quality = str(user.get("quality", "720"))

                # Second chance: short links resolve to an id we may know already.
                if len(canonicals) > 1 and await _try_cache(
                        message, canonicals, lang=lang, user=user,
                        user_id=user_id, url=url, force=force, status=status):
                    return

                if info and info.is_carousel:
                    await status.set("downloading_simple")
                    files = await Deps.downloader.download_carousel(
                        info, job, cookiefile=cookiefile, proxy=proxy, on_progress=status.progress)
                    if not files:
                        files = await fetch_gallery(url, job, cookiefile=cookiefile, proxy=proxy,
                                                     limit=Deps.settings.carousel_limit,
                                                     max_filesize=Deps.settings.max_filesize)
                    await deliver_album(message, files, lang=lang, user_id=user_id,
                                        url=url, title=info.title,
                                        canonicals=canonicals, status=status)
                    return

                kind = force or ("video" if info and info.has_video else None)
                if kind == "audio":
                    downloaded = await Deps.downloader.download_audio(
                        url, job, cookiefile=cookiefile, proxy=proxy, on_progress=status.progress)
                    await deliver_audio(
                        message, downloaded, job, lang=lang, user_id=user_id, url=url,
                        canonicals=canonicals,
                        set_primary=bool(info and not info.has_video),  # forced MP3 of a video keeps "video" primary
                        proxy=proxy, status=status)
                    return
                if kind == "video":
                    downloaded = await Deps.downloader.download_video(
                        url, job, cookiefile=cookiefile, proxy=proxy,
                        quality=quality, on_progress=status.progress)
                    await deliver_video(
                        message, downloaded, job, lang=lang, user_id=user_id, url=url,
                        canonicals=canonicals, quality=quality,
                        set_primary=bool(info is None or info.has_video),
                        proxy=proxy, status=status)
                    return
                if info and info.is_image:
                    downloaded = await Deps.downloader.download_image(
                        url, job, cookiefile=cookiefile, proxy=proxy)
                    await deliver_album(message, [downloaded], lang=lang, user_id=user_id,
                                        url=url, title=info.title,
                                        canonicals=canonicals, status=status)
                    return
                if kind is None and info is not None:
                    # Single non-video, non-image media ⇒ audio (SoundCloud & co.)
                    downloaded = await Deps.downloader.download_audio(
                        url, job, cookiefile=cookiefile, proxy=proxy, on_progress=status.progress)
                    await deliver_audio(
                        message, downloaded, job, lang=lang, user_id=user_id, url=url,
                        canonicals=canonicals, set_primary=True,
                        proxy=proxy, status=status)
                    return

                # Last resort: gallery-dl is brilliant at image-first sites.
                await status.set("downloading_simple")
                files = await fetch_gallery(url, job, cookiefile=cookiefile, proxy=proxy,
                                             limit=Deps.settings.carousel_limit,
                                             max_filesize=Deps.settings.max_filesize)
                await deliver_album(message, files, lang=lang, user_id=user_id, url=url,
                                    title=(info.title if info else ""),
                                    canonicals=canonicals, status=status)
    except MediaError as exc:
        log.info("media error for %s: %s", url, exc)
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, exc.i18n_key))
        await Deps.db.log_download(user_id, url, force or "media", "", status="error")
    except Exception:  # noqa: BLE001 — the show must go on
        log.exception("unexpected failure for %s", url)
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, "error_generic"))
    finally:
        if job:
            shutil.rmtree(job, ignore_errors=True)  # no leftovers, ever


@router.message(Command("audio"))
async def cmd_audio(message: Message, command: CommandObject) -> None:
    assert message.from_user
    lang, user = await _lang(message.from_user.id, message.from_user.language_code)
    if await _maintenance_block(message, lang):
        return
    url = _find_url(command.args)
    if not url:
        await message.answer(t(lang, "send_link_or_name"))
        return
    await process_url(message, url, lang=lang, user=user, force="audio")


@router.message(Command("video", "download"))
async def cmd_video(message: Message, command: CommandObject) -> None:
    assert message.from_user
    lang, user = await _lang(message.from_user.id, message.from_user.language_code)
    if await _maintenance_block(message, lang):
        return
    url = _find_url(command.args)
    if not url:
        await message.answer(t(lang, "send_link_or_name"))
        return
    await process_url(message, url, lang=lang, user=user, force="video")


@router.callback_query(F.data.startswith("mp3:"))
async def on_mp3_button(call: CallbackQuery) -> None:
    assert call.from_user and call.data and call.message
    lang, user = await _lang(call.from_user.id, call.from_user.language_code)
    url = Deps.tokens.get(call.data.split(":", 1)[1])
    await call.answer()
    if not url:
        await call.message.answer(t(lang, "search_expired"))  # type: ignore[union-attr]
        return
    msg = call.message
    assert isinstance(msg, Message)
    # Synthesize a message-like context: answer into the same chat.
    await process_url(msg, str(url), lang=lang, user=user, force="audio", actor_id=call.from_user.id)


# ── YouTube text search ──────────────────────────────────────────────────────
def _search_page_text(lang: str, query: str, results, page: int, page_size: int) -> str:
    pages = max(1, math.ceil(len(results) / page_size))
    start = page * page_size
    lines = [t(lang, "search_results", query=_esc(query), total=len(results),
               page=page + 1, pages=pages), ""]
    for offset, item in enumerate(results[start:start + page_size]):
        lines.append(f"<b>{start + offset + 1}.</b> {_esc(item.title)} "
                     f"· <code>{fmt_duration(item.duration)}</code>")
    return "\n".join(lines)


async def run_search(message: Message, query: str, *, lang: str, user_id: int,
                     origin: Message | None = None) -> None:
    status_msg = origin or await message.answer(
        t(lang, "searching", spinner=spinner_frame(), query=_esc(query)))
    status = StatusMessage(status_msg, lang)
    try:
        async with Deps.runtime.ytdlp_context(user_id) as (cookiefile, proxy):
            results = await Deps.downloader.search(query, cookiefile=cookiefile, proxy=proxy)
    except MediaError as exc:
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, exc.i18n_key))
        return
    except Exception:  # noqa: BLE001
        log.exception("search failed: %s", query)
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, "error_generic"))
        return
    if not results:
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, "search_empty"))
        return
    token = Deps.searches.put(query, results)
    size = Deps.settings.search_page_size
    with contextlib.suppress(Exception):
        await status_msg.edit_text(
            _search_page_text(lang, query, results, 0, size),
            reply_markup=kb.search_page_kb(lang, token, 0, results, size))


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    if await _maintenance_block(message, lang):
        return
    query = (command.args or "").strip()
    if not query:
        await message.answer(t(lang, "send_link_or_name"))
        return
    await run_search(message, query, lang=lang, user_id=message.from_user.id)


@router.callback_query(F.data.startswith("page:"))
async def on_page(call: CallbackQuery) -> None:
    assert call.from_user and call.data and call.message
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    _, token, page = call.data.split(":")
    found = Deps.searches.get(token)
    if not found:
        await call.answer(t(lang, "search_expired"), show_alert=True)
        return
    query, results = found
    page_no = int(page)
    size = Deps.settings.search_page_size
    msg = call.message
    assert isinstance(msg, Message)
    with contextlib.suppress(Exception):
        await msg.edit_text(_search_page_text(lang, query, results, page_no, size),
                            reply_markup=kb.search_page_kb(lang, token, page_no, results, size))
    await call.answer()


@router.callback_query(F.data.startswith("pick:"))
async def on_pick(call: CallbackQuery) -> None:
    assert call.from_user and call.data and call.message
    lang, user = await _lang(call.from_user.id, call.from_user.language_code)
    _, token, idx = call.data.split(":")
    found = Deps.searches.get(token)
    if not found or int(idx) >= len(found[1]):
        await call.answer(t(lang, "search_expired"), show_alert=True)
        return
    chosen = found[1][int(idx)]
    await call.answer(f"🎵 {chosen.title[:60]}")
    msg = call.message
    assert isinstance(msg, Message)
    with contextlib.suppress(Exception):
        await msg.delete()
    await process_url(msg, chosen.url, lang=lang, user=user, force="audio", actor_id=call.from_user.id)


# ── music recognition (Shazam) ───────────────────────────────────────────────
@router.message(F.video | F.video_note | F.animation)
async def on_incoming_video(message: Message) -> None:
    assert message.from_user
    if message.chat.type != "private":
        return  # in groups, wait for an explicit /shazam — manners!
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    media = message.video or message.video_note or message.animation
    assert media
    token = Deps.tokens.put({"file_id": media.file_id, "unique": media.file_unique_id,
                             "user_id": message.from_user.id})
    await message.answer(t(lang, "video_received"), reply_markup=kb.incoming_video_kb(lang, token))


@router.message(Command("shazam"))
async def cmd_shazam(message: Message, bot: Bot) -> None:
    assert message.from_user
    lang, _ = await _lang(message.from_user.id, message.from_user.language_code)
    reply = message.reply_to_message
    media = None
    if reply:
        media = reply.video or reply.video_note or reply.audio or reply.voice or reply.animation
    if media is None:
        await message.answer(t(lang, "shazam_hint"))
        return
    await _run_recognition(message, bot, media.file_id, lang=lang,
                           user_id=message.from_user.id, unique_id=getattr(media, 'file_unique_id', None))


async def _run_recognition(message: Message, bot: Bot, file_id: str, *, lang: str, user_id: int,
                           origin: Message | None = None, unique_id: str | None = None) -> None:
    status_msg = origin or await message.answer(t(lang, "shazam_working", spinner=spinner_frame()))
    job = _job_dir()
    try:
        track = None
        if unique_id:  # ⚡️ recognised this exact file before? Answer from memory.
            cached = await Deps.db.recognition_get(unique_id)
            if cached:
                track = RecognizedTrack(title=cached["title"], artist=cached["artist"],
                                        album=cached.get("album") or "",
                                        cover_url=cached.get("cover_url"),
                                        shazam_url=cached.get("shazam_url"))
        if track is None:
            tg_file = await bot.get_file(file_id)
            local = job / ("input" + Path(tg_file.file_path or ".mp4").suffix)
            await bot.download_file(tg_file.file_path, destination=str(local))  # type: ignore[arg-type]
            track = await recognize_file(local, job)
            if track and unique_id:
                await Deps.db.recognition_put(unique_id, title=track.title, artist=track.artist,
                                              album=track.album, cover_url=track.cover_url,
                                              shazam_url=track.shazam_url)
        if not track:
            with contextlib.suppress(Exception):
                await status_msg.edit_text(t(lang, "shazam_notfound"))
            return
        token = Deps.tokens.put(track.query)
        caption = t(lang, "shazam_found", artist=_esc(track.artist), title=_esc(track.title))
        if track.album:
            caption += f"\n💿 {_esc(track.album)}"
        markup = kb.recognized_kb(lang, token, track.shazam_url)
        if track.cover_url:
            cover = await _fetch_bytes(track.cover_url)
            if cover:
                cover_path = job / "rec.jpg"
                cover_path.write_bytes(cover)
                await message.answer_photo(FSInputFile(str(cover_path)), caption=caption, reply_markup=markup)
                with contextlib.suppress(Exception):
                    await status_msg.delete()
                return
        with contextlib.suppress(Exception):
            await status_msg.edit_text(caption, reply_markup=markup)
    except Exception:  # noqa: BLE001
        log.exception("recognition failed")
        with contextlib.suppress(Exception):
            await status_msg.edit_text(t(lang, "error_generic"))
    finally:
        shutil.rmtree(job, ignore_errors=True)


@router.callback_query(F.data.startswith("shazam:"))
async def on_shazam_button(call: CallbackQuery, bot: Bot) -> None:
    assert call.from_user and call.data and call.message
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    payload = Deps.tokens.get(call.data.split(":", 1)[1]) or {}
    await call.answer()
    msg = call.message
    assert isinstance(msg, Message)
    if not payload.get("file_id"):
        await msg.answer(t(lang, "search_expired"))
        return
    await _run_recognition(msg, bot, payload["file_id"], lang=lang,
                           user_id=call.from_user.id, unique_id=payload.get("unique"))


@router.callback_query(F.data.startswith("vaudio:"))
async def on_video_audio(call: CallbackQuery, bot: Bot) -> None:
    """Extract the full audio track from an uploaded video."""
    assert call.from_user and call.data and call.message
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    payload = Deps.tokens.get(call.data.split(":", 1)[1]) or {}
    await call.answer()
    msg = call.message
    assert isinstance(msg, Message)
    if not payload.get("file_id"):
        await msg.answer(t(lang, "search_expired"))
        return
    from ..config import resolve_ffmpeg
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        await msg.answer(t(lang, "error_generic"))
        return
    # ⚡️ Same video forwarded twice? The extracted MP3 is already on Telegram.
    ckey = upload_audio_key(payload.get("unique") or payload["file_id"])
    hit = await Deps.db.cache_get(ckey)
    if hit:
        try:
            await msg.answer_audio(hit["file_id"])
            return
        except Exception:  # noqa: BLE001 — stale id, extract again below
            await Deps.db.cache_delete(ckey)
    status = StatusMessage(await msg.answer(t(lang, "downloading_simple", spinner=spinner_frame())), lang)
    job = _job_dir()
    try:
        tg_file = await bot.get_file(payload["file_id"])
        local = job / ("input" + Path(tg_file.file_path or ".mp4").suffix)
        await bot.download_file(tg_file.file_path, destination=str(local))  # type: ignore[arg-type]
        out = job / "audio.mp3"
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", str(local), "-vn", "-b:a", "192k", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=600)
        if out.is_file():
            await status.set("uploading")
            sent = await msg.answer_audio(FSInputFile(str(out)))
            if sent.audio:
                await Deps.db.cache_put(ckey, sent.audio.file_id, "audio",
                                        sent.audio.title or "", sent.audio.performer or "",
                                        sent.audio.duration or 0)
            await status.delete()
        else:
            await msg.answer(t(lang, "error_generic"))
    except Exception:  # noqa: BLE001
        log.exception("video→audio failed")
        await msg.answer(t(lang, "error_generic"))
    finally:
        shutil.rmtree(job, ignore_errors=True)


@router.callback_query(F.data.startswith("recmp3:"))
async def on_rec_mp3(call: CallbackQuery) -> None:
    assert call.from_user and call.data and call.message
    lang, user = await _lang(call.from_user.id, call.from_user.language_code)
    query = Deps.tokens.get(call.data.split(":", 1)[1])
    await call.answer()
    msg = call.message
    assert isinstance(msg, Message)
    if not query:
        await msg.answer(t(lang, "search_expired"))
        return
    # Search, grab the top hit, deliver it as MP3 — musical telepathy, basically.
    try:
        async with Deps.runtime.ytdlp_context(call.from_user.id) as (cookiefile, proxy):
            results = await Deps.downloader.search(str(query), cookiefile=cookiefile, proxy=proxy)
    except MediaError:
        results = []
    if results:
        await process_url(msg, results[0].url, lang=lang, user=user, force="audio", actor_id=call.from_user.id)
    else:
        await msg.answer(t(lang, "search_empty"))


@router.callback_query(F.data.startswith("recsearch:"))
async def on_rec_search(call: CallbackQuery) -> None:
    assert call.from_user and call.data and call.message
    lang, _ = await _lang(call.from_user.id, call.from_user.language_code)
    query = Deps.tokens.get(call.data.split(":", 1)[1])
    await call.answer()
    msg = call.message
    assert isinstance(msg, Message)
    if not query:
        await msg.answer(t(lang, "search_expired"))
        return
    await run_search(msg, str(query), lang=lang, user_id=call.from_user.id)


# ── catch-all: links & song names in plain text ──────────────────────────────
@router.message(F.text)
async def on_text(message: Message) -> None:
    assert message.from_user and message.text
    if message.text.startswith("/"):
        return
    lang, user = await _lang(message.from_user.id, message.from_user.language_code)
    if await _maintenance_block(message, lang):
        return
    url = _find_url(message.text)
    if url:
        if message.chat.type != "private":
            return  # groups have /download & /audio for a reason
        await process_url(message, url, lang=lang, user=user)
        return
    if message.chat.type == "private":
        query = message.text.strip()
        if 2 <= len(query) <= 120:
            await run_search(message, query, lang=lang, user_id=message.from_user.id)
        else:
            await message.answer(t(lang, "send_link_or_name"))
