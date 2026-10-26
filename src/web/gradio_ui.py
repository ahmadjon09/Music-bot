"""Public landing page (Gradio) — deliberately content-free.

Visitors of the Space see a single line and nothing else: no stats, no
buttons, no version numbers. Everything interesting (the bot itself and the
admin Mini App) lives inside Telegram, away from curious eyes.
"""

from __future__ import annotations

import gradio as gr

# Hide Gradio's own footer too — bare page, bare minimum.
_CSS = "footer { display: none !important; } .gradio-container { max-width: 100% !important; }"

_PAGE = (
    '<div style="display:flex; align-items:center; justify-content:center; '
    'min-height:70vh; font-family:system-ui, sans-serif;">'
    '<div style="font-size:2.2rem; font-weight:700; letter-spacing:.02em;">'
    "In deployment</div></div>"
)


def build_gradio() -> gr.Blocks:
    with gr.Blocks(title="In deployment", css=_CSS) as demo:
        gr.HTML(_PAGE)
    return demo
