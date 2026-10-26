---
title: Music Bot
emoji: 🎧
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
---

# 🎧 Music Bot — Ultra-Fast Telegram Media Downloader

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-powered-FF0000)](https://github.com/yt-dlp/yt-dlp)
[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97-Hugging%20Face%20Spaces-yellow)](https://huggingface.co/spaces)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](#license)

Send the bot a **link**, a **song name**, or a **video** — it handles the rest:
instant media downloads from 1000+ sites, paginated YouTube song search, and
Shazam-powered music recognition. Async end-to-end, engineered to stay fast
and lean on free-tier hardware (Hugging Face Spaces included).

Built on the shoulders of [ssebastianoo/yt-dlp-telegram](https://github.com/ssebastianoo/yt-dlp-telegram) —
re-architected as a modular, fully-async aiogram 3 application.

## ✨ Features

| | |
|---|---|
| 🔗 **Universal downloader** | YouTube, TikTok, Instagram, X/Twitter, Pinterest, Bluesky, SoundCloud + everything yt-dlp & gallery-dl support |
| 🖼 **Carousel / album support** | Multi-item posts arrive as clean Telegram albums (chunked by 10, capped at 20) |
| 🔍 **Song search** | Type a name → **20+ results under 10 minutes**, **10 per page**, inline pagination, one-tap MP3 |
| ⚡️ **file_id cache** | The same track requested twice is re-sent instantly — zero re-downloading |
| 🎵 **Music recognition** | Send any video → the bot names the background track (Shazam, free, no API key) and offers the MP3 |
| 🏷 **Rich metadata** | Cleaned titles, artist/title splitting, embedded cover art (ID3/MP4 tags), HQ thumbnails |
| 🌍 **3 languages** | 🇺🇿 O'zbek · 🇷🇺 Русский · 🇬🇧 English — per-user, switchable in Settings |
| 🌐 **Adaptive proxies** | Paste proxies in *any* vendor format; pooled, randomly rotated, changed live |
| 🍪 **Live cookies** | Global (admin) + per-user cookies, Fernet-encrypted, swapped without restarts |
| 🛠 **Admin Mini App** | Telegram Web App for admins only: stats, proxy test/apply, cookies, maintenance, housekeeping |
| 🎞 **Quality prefs** | Per-user video quality (360p–1080p/Best) persisted in SQLite |
| 🧹 **Zero-waste runtime** | One process, one port, per-job temp dirs always cleaned, process-group kills — no zombies |

## 🗺 Architecture

```
┌────────────────────────── single process · port 7860 ──────────────────────────┐
│  app.py — FastAPI + Gradio (mount) + aiogram polling (background task)         │
│                                                                                 │
│  GET /            Gradio public status page (read-only)                         │
│  GET /admin       Telegram Mini App  ── initData HMAC ──► /api/admin/*          │
│  GET /health      liveness probe                                                │
│                                                                                 │
│  src/                                                                           │
│  ├─ bot/      handlers · keyboards · state (search sessions, tokens, gate)      │
│  ├─ downloader.py   yt-dlp engine (threads + throttled progress bridge)         │
│  ├─ gallery.py      gallery-dl fallback for image-first posts                   │
│  ├─ recognize.py    ffmpeg snippet → Shazam                                     │
│  ├─ metadata.py     title cleanup · artist split · mutagen tags · cover art     │
│  ├─ proxy.py        forgiving multi-format proxy parser (see below)             │
│  ├─ runtime.py      live proxy pool + cookie jar (hot-swappable)                │
│  ├─ security.py     Fernet encryption · Web App initData validation             │
│  ├─ db.py           SQLite (users, kv, cookies, file_id cache, download log)    │
│  ├─ i18n.py         uz / ru / en strings                                        │
│  └─ web/            FastAPI admin API · Gradio UI · Mini App page               │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Download pipeline (the fast path):** probe URL → check `file_id` cache →
yt-dlp in a worker thread (native M4A/MP3 preferred — no re-encode; ffmpeg only
as a last resort) → tag & embed cover → upload → cache the `file_id` → wipe the
temp dir. Progress is streamed into a single edited message with an animated
bar, speed and ETA.

## 🚀 Quick start

### Option A — Hugging Face Spaces (free) ☁️

1. Create a Space → **Gradio** SDK (this repo's `README` front-matter already declares it).
2. Push this repository to the Space (the included GitHub Action can do it for you — add an `HF_TOKEN` repo secret and edit the Space path in `.github/workflows/deploy.yml`).
3. In **Space → Settings → Variables and secrets**, add secrets:
   - `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `ADMIN_IDS` — your numeric Telegram ID (send `/id` to the bot later, or ask [@userinfobot](https://t.me/userinfobot))
   - `SECRET_KEY` — any long random string
4. Wait for the build (`ffmpeg` + `nodejs` come from `packages.txt`). Done — message your bot!

> The public URL is auto-derived from `SPACE_ID`; set `PUBLIC_BASE_URL` only if you use a custom domain.

### Option B — Docker (any VPS)

```bash
git clone https://github.com/ahmadjon09/Music-bot && cd Music-bot
cp .env.example .env      # fill in BOT_TOKEN, ADMIN_IDS, SECRET_KEY
docker compose up -d --build
docker compose logs -f bot   # → "bot online as @yourbot 🎧"
```

### Option C — Local / bare metal

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit it
python app.py             # web on http://0.0.0.0:7860 + bot polling
```

> `ffmpeg` is required for media conversion/recognition. If a system ffmpeg is
> missing, the bundled `imageio-ffmpeg` wheel supplies a static binary.
> `node` is optional (helps yt-dlp solve some YouTube challenges).

## 🤖 Bot usage

| Action | Result |
|---|---|
| Send a **link** | Original media (video/photo/carousel) + 🎵 MP3 button under videos |
| `/audio <url>` | MP3/M4A with tags + cover art |
| `/video <url>` | Force video download |
| Type a **song name** | YouTube search, 10/page pagination, tap a number → MP3 |
| `/search <name>` | Same search, explicitly |
| Send a **video** (private chat) | 🎵 *Identify the song* / 🎧 *Extract audio* buttons |
| Reply to a video with `/shazam` | Music recognition |
| `/settings`, `/lang` | Language (uz/ru/en) + video quality |
| `/cookies` | Upload personal `cookies.txt` (encrypted) for restricted content |
| `/status`, `/id`, `/help` | Bot stats / your ID / help |
| `/admin` *(admins)* | Opens the Admin Mini App |
| `/setproxy <raw>` *(admins)* | Apply a new proxy pool instantly (`off` clears it) |
| `/stats` *(admins)* | Numbers at a glance |

Group chats: use the commands (`/audio`, `/video`, `/search`) — the bot stays
quiet otherwise. Manners matter.

## 🌐 Proxy formats accepted

Vendors disagree on credential layouts; we accept them all. Multiple proxies
( one per line / comma-separated ) form a rotating pool:

```
host:port
host:port:username:password
username:password:host:port
username:password@host:port
host:port@username:password
socks5://username:password@host:port
[ipv6]:port
```

Example: `silver.ciaude.co.uk:8080:myuser:mypass` → `http://myuser:mypass@silver.ciaude.co.uk:8080`.
Passwords are always masked ( `•••` ) in the admin panel and logs.

## 🍪 Cookies

Export a Netscape-format `cookies.txt` from your browser (e.g. with the
“Get cookies.txt LOCALLY” extension) and either:

- **Admins:** paste/upload it in the Mini App (or just send the file to the bot) → becomes the *global* jar, applied instantly.
- **Users:** `/cookies` then send the file → stored per-user, takes precedence over the global jar.

Everything is validated (format + ≤1 MB), encrypted with Fernet (`SECRET_KEY`),
materialised to a `0600` temp file only for the duration of a download, then deleted.

## 🛠 Admin Mini App

Admins receive a **🛠 Admin panel** button (`/start`, `/admin`) that opens
`{PUBLIC_BASE_URL}/admin` as a Telegram Web App. Every API call carries
Telegram `initData`, verified server-side with HMAC-SHA256 (`WebAppData` key)
plus an `ADMIN_IDS` check and a 24 h freshness window.

From the panel you can: view stats & recent downloads, **test and apply proxies
live**, install/remove global cookies, toggle maintenance mode, and clear the
file-id cache or temp files — all without a single restart.

## ⚙️ Configuration

All configuration is environment variables (see [`.env.example`](.env.example)):

| Variable | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token |
| `ADMIN_IDS` | ✅ | Comma-separated admin user IDs |
| `SECRET_KEY` | ✅ | Encrypts stored cookies |
| `PUBLIC_BASE_URL` | – | Base URL for the Web App button (auto-derived on HF) |
| `PROXY` | – | Initial proxy pool (admin panel can override live) |
| `MAX_FILESIZE_MB` | – | Per-file cap (default `49`, Telegram's practical limit) |
| `MAX_GLOBAL_DOWNLOADS` | – | Global concurrent downloads (default `3`) |
| `SEARCH_MAX_DURATION` | – | Search filter, seconds (default `600` = 10 min) |
| `DATA_DIR` | – | Where `bot.db` & temp files live |
| `DEBUG_ADMIN=1` | – | ⚠️ local dev only: opens the Admin API without initData |

## 🧪 Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Covers the proxy parser (every vendor shape), title cleanup & artist splitting,
i18n parity across all three languages, Web App HMAC validation, cookie
encryption/validation, and media-routing logic.

## 🙏 Credits

- Original single-file bot: [ssebastianoo/yt-dlp-telegram](https://github.com/ssebastianoo/yt-dlp-telegram)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [gallery-dl](https://github.com/mikf/gallery-dl) · [aiogram](https://github.com/aiogram/aiogram) · [shazamio](https://github.com/shazamio/ShazamIO)

## License

MIT — do your best, credit nicely. Respect the terms of the sites you download
from and the rights of content owners; this tool is for personal use.
