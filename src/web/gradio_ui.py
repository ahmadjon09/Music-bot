"""Public status page (Gradio) — what visitors of the Space see.

Deliberately read-only: all the sharp tools live in the Telegram Mini App,
which only admins can open. This page just proves the bot is alive.
"""

from __future__ import annotations

import gradio as gr

from .. import __version__
from ..bot.state import uptime_text
from ..config import Settings
from ..db import Database
from ..downloader import ytdlp_version
from ..runtime import Runtime


def build_gradio(settings: Settings, db: Database, runtime: Runtime) -> gr.Blocks:
    async def refresh() -> tuple[str, str, str, str, str]:
        stats = await db.stats()
        bot_state = "🟢 online" if settings.token_looks_valid else "🔴 BOT_TOKEN not set"
        return (
            bot_state,
            uptime_text(),
            f"{stats['users']} users · {stats['downloads']} downloads · {stats['cached']} cached files",
            f"yt-dlp {ytdlp_version()} · bot v{__version__}",
            "🔐 " + (runtime.proxy_label() if False else "Admin settings are private"),
        )

    with gr.Blocks(title="Music Bot — status", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# 🎧 Music Bot\n"
            "A blazing-fast Telegram media downloader: **YouTube · TikTok · Instagram · X · "
            "Pinterest** and 1000+ more sites, song search, and Shazam-powered music recognition.\n\n"
            "👉 Open the bot in Telegram and just send a link, a song name — or a video."
        )
        status = gr.Textbox(label="Bot", interactive=False)
        uptime = gr.Textbox(label="Uptime", interactive=False)
        counters = gr.Textbox(label="Counters", interactive=False)
        versions = gr.Textbox(label="Versions", interactive=False)
        note = gr.Textbox(label="Admin", interactive=False)
        refresh_btn = gr.Button("🔄 Refresh", variant="primary")
        refresh_btn.click(refresh, outputs=[status, uptime, counters, versions, note])
        demo.load(refresh, outputs=[status, uptime, counters, versions, note])
        gr.Markdown(
            "<small>Administration happens inside Telegram via the secure Mini App "
            "(admins only, verified with Telegram initData).</small>"
        )
    return demo
