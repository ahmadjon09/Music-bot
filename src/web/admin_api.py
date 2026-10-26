"""Admin Mini App backend — FastAPI routes, guarded by Telegram Web App auth.

Every /api/admin/* call must carry valid Telegram ``initData``
(``X-Telegram-Init-Data`` header) signed with the bot token, and belong to
an ADMIN_IDS user. No initData, no cookies, no exceptions — the panel can
swap proxies & cookies live, so the door stays properly locked.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import aiohttp
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import __version__, security
from ..bot.state import BOT_STARTED_AT, uptime_text
from ..config import Settings, resolve_ffmpeg
from ..db import Database
from ..downloader import ytdlp_version
from ..proxy import ProxyParseError, parse_proxy_list
from ..runtime import Runtime

_STATIC = Path(__file__).resolve().parent / "static"


class ProxyBody(BaseModel):
    proxies: str


class CookiesBody(BaseModel):
    content: str


class MaintenanceBody(BaseModel):
    enabled: bool


def build_admin_router(settings: Settings, db: Database, runtime: Runtime) -> APIRouter:
    router = APIRouter()

    async def require_admin(
        x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    ) -> int:
        if settings.debug_admin:  # local development only — see .env.example
            return 0
        user_id = security.init_data_user_id(x_telegram_init_data, settings.bot_token)
        if user_id is None or not settings.is_admin(user_id):
            raise HTTPException(status_code=403, detail="Admins only")
        return user_id

    # ── the Mini App page itself ─────────────────────────────────────────────
    @router.get("/admin", include_in_schema=False)
    async def admin_page() -> FileResponse:
        return FileResponse(_STATIC / "admin.html", media_type="text/html")

    @router.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True, "version": __version__, "uptime": uptime_text()}

    # ── state ────────────────────────────────────────────────────────────────
    @router.get("/api/admin/state")
    async def state(_: int = Depends(require_admin)) -> dict:
        stats = await db.stats()
        cookies = runtime.global_cookies_report()
        tmp_usage = 0
        try:
            tmp_usage = sum(p.stat().st_size for p in settings.tmp_dir.rglob("*") if p.is_file())
        except OSError:
            pass
        return {
            "version": __version__,
            "started_at": BOT_STARTED_AT,
            "uptime": uptime_text(),
            "now": time.time(),
            "users": stats["users"],
            "downloads": stats["downloads"],
            "cached_files": stats["cached"],
            "cache": await db.cache_stats(),
            "ytdlp": ytdlp_version(),
            "ffmpeg": bool(resolve_ffmpeg()),
            "maintenance": runtime.maintenance,
            "tmp_bytes": tmp_usage,
            "proxies": [p.masked for p in runtime.proxies],
            "cookies": {
                "installed": runtime.has_global_cookies,
                "total": cookies.get("total", 0),
                "domains": cookies.get("domains", {}),
            },
            "recent": await db.recent_downloads(15),
        }

    # ── proxy management (live switch, no restart) ──────────────────────────
    @router.post("/api/admin/proxy")
    async def set_proxy(body: ProxyBody, _: int = Depends(require_admin)) -> dict:
        try:
            pool = await runtime.set_proxies(body.proxies)
        except ProxyParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "proxies": [p.masked for p in pool]}

    @router.delete("/api/admin/proxy")
    async def clear_proxy(_: int = Depends(require_admin)) -> dict:
        await runtime.clear_proxies()
        return {"ok": True}

    @router.post("/api/admin/proxy/test")
    async def test_proxy(body: ProxyBody, _: int = Depends(require_admin)) -> dict:
        """Try one request through the (first) candidate proxy."""
        try:
            pool = parse_proxy_list(body.proxies)
        except ProxyParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not pool:
            raise HTTPException(status_code=400, detail="No proxy given")
        proxy_url = pool[0].url
        started = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://api.ipify.org?format=json", proxy=proxy_url) as resp:
                    data = await resp.json(content_type=None)
            return {"ok": True, "ip": data.get("ip", "?"),
                    "ms": int((time.monotonic() - started) * 1000)}
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    # ── cookies management (live switch, no restart) ────────────────────────
    @router.post("/api/admin/cookies")
    async def set_cookies(body: CookiesBody, _: int = Depends(require_admin)) -> dict:
        report = security.validate_cookies(body.content)
        if not report["ok"]:
            raise HTTPException(status_code=400, detail=report["error"])
        await runtime.set_global_cookies(body.content)
        return {"ok": True, "total": report["total"], "domains": report["domains"]}

    @router.post("/api/admin/cookies/upload")
    async def upload_cookies(file: UploadFile = File(...), _: int = Depends(require_admin)) -> dict:
        raw = await file.read()
        content = raw.decode(errors="ignore")
        report = security.validate_cookies(content)
        if not report["ok"]:
            raise HTTPException(status_code=400, detail=report["error"])
        await runtime.set_global_cookies(content)
        return {"ok": True, "total": report["total"], "domains": report["domains"]}

    @router.delete("/api/admin/cookies")
    async def clear_cookies(_: int = Depends(require_admin)) -> dict:
        await runtime.clear_global_cookies()
        return {"ok": True}

    # ── maintenance & housekeeping ───────────────────────────────────────────
    @router.post("/api/admin/maintenance")
    async def maintenance(body: MaintenanceBody, _: int = Depends(require_admin)) -> dict:
        await runtime.set_maintenance(body.enabled)
        return {"ok": True, "maintenance": runtime.maintenance}

    @router.post("/api/admin/clear-cache")
    async def clear_cache(_: int = Depends(require_admin)) -> dict:
        removed = await db.cache_clear()
        return {"ok": True, "removed": removed}

    @router.post("/api/admin/clear-tmp")
    async def clear_tmp(_: int = Depends(require_admin)) -> dict:
        def _wipe() -> None:
            for child in settings.tmp_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)

        await asyncio.to_thread(_wipe)
        return {"ok": True}

    return router
