"""Entry point — one process, one event loop, one port (7860).

Layout of the single process:
  * FastAPI app
      ├─ GET  /            → bare "In deployment" placeholder (no info, no UI)
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

# ── ZeroGPU compatibility shim (must run before gradio is imported) ─────────
# Some Hugging Face Spaces sit on ZeroGPU hardware, which kills the container
# during startup ("No @spaces.GPU function detected during startup") unless
# the app defines a @spaces.GPU function. This bot is pure CPU work, so we
# register a tiny no-op purely to satisfy that platform check. Off ZeroGPU the
# decorator is a no-op; without the `spaces` package nothing changes at all.
try:
    import spaces

    @spaces.GPU(duration=1)
    def _zerogpu_warmup() -> str:  # never called — its existence is the point
        return "ok"
except Exception:  # noqa: BLE001 — CPU Spaces / local runs simply skip this
    spaces = None  # type: ignore[assignment]

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

    # No public API docs either — /docs would list every admin endpoint.
    app = FastAPI(title="Music Bot", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(build_admin_router(settings, db, runtime))

    # Gradio's mounted sub-app would otherwise serve its own API schema at
    # /openapi.json — shadow those paths so literally nothing is discoverable.
    from fastapi import HTTPException

    @app.get("/openapi.json", include_in_schema=False)
    @app.get("/docs", include_in_schema=False)
    @app.get("/redoc", include_in_schema=False)
    async def _gone() -> None:
        raise HTTPException(status_code=404)

    demo = build_gradio()  # public page: a bare "In deployment" placeholder
    app = gr.mount_gradio_app(app, demo, path="/")
    return app


app = create_app()


def _report_zerogpu_startup() -> None:
    """Send ZeroGPU's startup report by hand.

    `spaces` normally hooks the report into ``gradio.Blocks.launch()``, but we
    serve through FastAPI + uvicorn and never call ``launch()`` — so without
    this, ZeroGPU never learns about our @spaces.GPU shim and kills us anyway.
    A no-op everywhere except ZeroGPU Spaces.
    """
    try:
        from spaces import zero

        startup = getattr(zero, "startup", None)
        if callable(startup):
            startup()
            cache = getattr(getattr(zero, "decorator", None), "decorated_cache", {})
            log.info("ZeroGPU startup report sent (%d GPU function(s) registered)", len(cache))
    except Exception:  # noqa: BLE001 — a failed report must never kill the bot
        log.debug("ZeroGPU startup report skipped", exc_info=True)


if __name__ == "__main__":
    _report_zerogpu_startup()
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")
