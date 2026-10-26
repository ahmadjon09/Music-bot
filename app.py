"""Entry point — one process, one event loop, one port (7860).

Layout of the single process:
  * FastAPI app
      ├─ GET  /            → Gradio status page (public, read-only)
      ├─ GET  /admin       → Telegram Mini App (admins only, initData-verified)
      ├─ /api/admin/*      → live proxy/cookies/stats control
      └─ GET  /health      → liveness probe
  * aiogram bot polling runs as a background task in the same loop.
    One process ⇒ no zombie ports, no orphaned workers, minimal RAM.

On Hugging Face (Gradio Spaces) this file is the app entry; in Docker it is
the container command; locally it's just ``python app.py``.
If BOT_TOKEN is missing we still serve the web layer, so a freshly created
Space shows a helpful page instead of crash-looping.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import gradio as gr
import uvicorn
from fastapi import FastAPI

from src.bot.factory import build_bot, build_dispatcher, register_commands
from src.config import settings
from src.db import Database
from src.downloader import Downloader
from src.runtime import Runtime
from src.web.admin_api import build_admin_router
from src.web.gradio_ui import build_gradio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
# yt-dlp & friends can be chatty; keep the logs readable on free tiers.
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
log = logging.getLogger("musicbot")


def create_app() -> FastAPI:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    runtime = Runtime(settings=settings, db=db)
    downloader = Downloader(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await db.open()
        await runtime.load()
        log.info("runtime ready · proxies: %s · global cookies: %s",
                 runtime.proxy_label(), "yes" if runtime.has_global_cookies else "no")

        bot = dp = polling_task = None
        if settings.token_looks_valid:
            bot = build_bot(settings)
            dp = build_dispatcher(settings, db, runtime, downloader)
            try:
                me = await bot.get_me()
                await register_commands(bot)
                log.info("bot online as @%s 🎧", me.username)
            except Exception:  # noqa: BLE001 — web layer must survive Telegram hiccups
                log.exception("Telegram unreachable at boot; polling will keep retrying")
            polling_task = asyncio.create_task(dp.start_polling(bot), name="bot-polling")
        else:
            log.warning("BOT_TOKEN is not set — web-only mode. Set it in Space Secrets.")

        try:
            yield
        finally:  # graceful shutdown: stop polling, close sessions, no zombies
            if dp is not None:
                with suppress(Exception):
                    await dp.stop_polling()
            if polling_task is not None:
                polling_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await polling_task
            if bot is not None:
                with suppress(Exception):
                    await bot.session.close()
            await db.close()

    app = FastAPI(title="Music Bot", lifespan=lifespan)
    app.include_router(build_admin_router(settings, db, runtime))

    demo = build_gradio(settings, db, runtime)
    app = gr.mount_gradio_app(app, demo, path="/")
    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")
