---
title: Music Bot
emoji: 🎧
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: 5.50.0
python_version: 3.11
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
instant media downloads from 1000+ sites, paginated Dydki.net song search, and
Shazam-powered music recognition. Async end-to-end, engineered to stay fast
and lean on free-tier hardware (Hugging Face Spaces included).

Built on the shoulders of [ssebastianoo/yt-dlp-telegram](https://github.com/ssebastianoo/yt-dlp-telegram) —
re-architected as a modular, fully-async aiogram 3 application.

## ✨ Features

| | |
|---|---|
| 🔗 **Universal downloader** | YouTube, TikTok, Instagram, X/Twitter, Pinterest, Bluesky, SoundCloud + everything yt-dlp & gallery-dl support |
| 🖼 **Carousel / album support** | Multi-item posts arrive as clean Telegram albums (chunked by 10, capped at 20) |
| 🔍 **Song search** | Type a name → search Dydki.net for tracks (artist, duration and ready MP3 stream), **10 per page**, inline pagination, one-tap MP3, artist artwork and a persistent Telegram `file_id` cache |
| ⚡ **Cobalt fast lane** | Instagram, TikTok, X, Pinterest, Facebook, Reddit, Vimeo… fetched via [Cobalt](https://cobalt.tools) in one POST (carousels included); yt-dlp stays on YouTube & audio duty, and doubles as the automatic fallback |
| 🤖 **Self-maintaining proxy pool** | A background worker scans the public [TheSpeedX proxy lists](https://github.com/TheSpeedX/PROXY-List) top-down, keeps only proxies that **actually reach YouTube**, ranks them by latency and re-scans every 15 min — downloads rotate through the best exits and cool down dead ones automatically, no babysitting |
| ⚡️ **Universal file_id cache** | **Everything** the bot sends (audio, video per quality, photos, whole carousels, extracted audio, Shazam results) is remembered in SQLite by Telegram `file_id`. Any URL spelling (`youtu.be/…`, Shorts, tracking params…) canonicalises to one key, checked *before* any network call — repeat requests are re-sent from Telegram's own servers in ~0s, for every user |
| 🎵 **Music recognition** | Send any video → the bot names the background track (Shazam, free, no API key) and offers the MP3 |
| 🏷 **Rich metadata** | Cleaned titles, artist/title splitting, embedded cover art (ID3/MP4 tags), HQ thumbnails |
| 🌍 **3 languages** | 🇺🇿 O'zbek · 🇷🇺 Русский · 🇬🇧 English — per-user, switchable in Settings |
| 🌐 **Adaptive proxies** | Paste proxies in *any* vendor format; manual pool or auto pool, rotated per attempt, changed live |
| 🍪 **Live cookies** | Global (admin) + per-user cookies, Fernet-encrypted, swapped without restarts |
| 🛠 **Admin Mini App** | Telegram Web App for admins only: stats, proxy test/apply, cookies, maintenance, housekeeping |
| 🎞 **Quality prefs** | Per-user video quality (360p–1080p/Best) persisted in SQLite |
| 🧹 **Zero-waste runtime** | One process, one port, per-job temp dirs always cleaned, process-group kills — no zombies |

## 🗺 Architecture

```
┌────────────────────────── single process · port 7860 ──────────────────────────┐
│  app.py — FastAPI + Gradio (mount) + aiogram polling (background task)         │
│                                                                                 │
│  GET /            bare “In deployment” placeholder (nothing public)            │
│  GET /admin       Telegram Mini App  ── initData HMAC ──► /api/admin/*          │
│  GET /health      liveness probe                                                │
│                                                                                 │
│  src/                                                                           │
│  ├─ bot/      handlers · keyboards · state (search sessions, tokens, gate)      │
│  ├─ downloader.py   yt-dlp engine (threads + throttled progress bridge)         │
│  ├─ gallery.py      gallery-dl fallback for image-first posts                   │
│  ├─ recognize.py    ffmpeg snippet → Shazam                                     │
│  ├─ metadata.py     title cleanup · artist split · mutagen tags · cover art     │
│  ├─ dydki.py        Dydki.net search cards · direct MP3 stream · query cache    │
│  ├─ artwork.py      optional artist portraits for Telegram audio thumbnails    │
│  ├─ proxy.py        forgiving multi-format proxy parser (see below)             │
│  ├─ proxypool.py    self-maintaining free-proxy pool (YouTube-verified)         │
│  ├─ cobalt.py       Cobalt API client — socials fast lane                       │
│  ├─ httputil.py     aiohttp sessions for HTTP + SOCKS proxies                   │
│  ├─ runtime.py      live proxy pool + cookie jar (hot-swappable)                │
│  ├─ security.py     Fernet encryption · Web App initData validation             │
│  ├─ db.py           SQLite (users, kv, cookies, file_id cache, download log)    │
│  ├─ i18n.py         uz / ru / en strings                                        │
│  └─ web/            FastAPI admin API · Gradio UI · Mini App page               │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Download pipeline (the fast path):** canonicalise URL → ⚡ **cache lookup
before any network request** (a `media_index` remembers whether a link *is* an
audio/video/photo/album, videos are keyed per quality) → probe → ⚡ cache lookup
again under the resolved `extractor:id` (rescues short links like `vm.tiktok.com`)
→ yt-dlp in a worker thread (native M4A/MP3 preferred — no re-encode; ffmpeg only
as a last resort) → tag & embed cover → upload → store every resulting `file_id`
(carousels as one ordered JSON payload) under *all* canonical spellings → wipe
the temp dir. Stale `file_id`s evict themselves and fall back to a fresh
download. Progress is streamed into a single edited message with an animated
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

> **ZeroGPU note:** if your Space runs on ZeroGPU hardware, Hugging Face normally
> refuses to start CPU-only apps (*“No @spaces.GPU function detected during
> startup”*). This repo handles that automatically: `app.py` registers a no-op
> `@spaces.GPU` shim and sends the ZeroGPU startup report explicitly (needed
> because serving goes through FastAPI/uvicorn, not `Blocks.launch()`). CPU
> Basic remains the ideal hardware for a 24/7 bot if your account offers it.
>
> **Keep-alive tip:** free Spaces sleep when idle. Point a free uptime monitor
> (e.g. UptimeRobot, 5-minute interval) at `https://<your-space>.hf.space/health`
> to keep the bot awake — the endpoint answers `{"ok": true, ...}`.

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
| Type a **song name** | Search Dydki.net, 10/page pagination, tap a number → MP3 |
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

### 🌀 Cloudflare WARP on a VPS (recommended against YouTube blocks)

YouTube flags most datacenter IPs (*"Sign in to confirm you're not a bot"*).
Cloudflare WARP in **proxy mode** gives yt-dlp a Cloudflare exit IP through a
local SOCKS5 endpoint — no full-tunnel VPN, SSH and system routes untouched.

**Native (Debian/Ubuntu):**

```bash
sudo bash scripts/install_warp.sh     # installs + registers + proxy mode @40000
# then either .env:  WARP_PROXY=socks5://127.0.0.1:40000
# or Admin Mini App → Proxy pool → "🌀 Use WARP (local)" → Test → Apply
```

**Docker:** a ready-made sidecar ([caomingjun/warp](https://github.com/cmj2002/warp-docker)):

```bash
docker compose --profile warp up -d   # starts bot + warp
# .env:  PROXY=socks5://warp:1080
```

> WARP needs `NET_ADMIN`/TUN, so it cannot run *inside* a Hugging Face Space.
> On HF, keep using cookies + a regular proxy (and the built-in player-client
> fallbacks); on your own VPS, WARP is the reliable route.

### 🤖 Autonomous free-proxy pool (on by default)

Free public proxy lists refresh every few minutes and most entries are dead
on arrival — perfect job for a robot, terrible job for a human. A background
worker (`src/proxypool.py`):

1. pulls the [TheSpeedX lists](https://github.com/TheSpeedX/PROXY-List)
   (`http.txt`, then `socks5.txt`, then `socks4.txt`) plus a small built-in
   bootstrap seed of previously measured proxies,
2. probes candidates **top-to-bottom** against YouTube's `generate_204`
   endpoint (40 in parallel) and stops as soon as the pool is full,
3. keeps the survivors ranked by latency, persists them across restarts,
   and re-scans every `PROXY_REFRESH_MINUTES` (default 15).

Every download/search then rotates through the best exits; a proxy that
fails is put in a 5-minute penalty box, a success clears its record. Two
modes, switchable live in the Admin Mini App (**🤖 Auto pool / ✋ Manual**,
plus **🔍 Rescan now**): manual pins your own proxies (WARP, paid ones),
auto uses the robot pool and falls back to manual entries while warming up.
Only public HTTPS download traffic ever goes through public proxies — never
bot tokens or user data.

## ⚡ Cobalt fast lane & Dydki music search

**Social links** (Instagram, TikTok, X, Pinterest, Facebook, Reddit, Vimeo,
Snapchat, Tumblr, Twitch clips, Bilibili…) go through
[Cobalt](https://github.com/imputnet/cobalt) first: one POST returns direct
or tunneled file URLs, and carousels arrive as picker items that become
Telegram albums. Any Cobalt miss falls back to yt-dlp, then gallery-dl —
three engines deep before we give up. yt-dlp keeps everything YouTube and
explicit media-link audio requests. Default is the public `api.cobalt.tools` instance;
for heavier use self-host (`docker compose --profile cobalt up -d`, then
`COBALT_API_URL=http://cobalt:9000`).

**Song-name search** reads Dydki.net's server-rendered `div.chkd` results: it
uses each card's `data-mp3` stream URL plus the listed artist and duration,
then sends that MP3 directly through Telegram (with a local-fetch fallback).
Search results are cached for 10 minutes; successfully sent tracks are cached
persistently by Telegram `file_id`, and an optional Deezer lookup adds an
artist portrait as the audio thumbnail. Shazam-recognized titles use the same
Dydki search path. YouTube remains supported for ordinary media links.

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
live**, install/remove global cookies, toggle maintenance mode, clear the
file-id cache (with hit statistics) or temp files — and **♻️ reset the bot's
public identity** (name, descriptions, command menu in every language) —
all without a single restart.

### 🤖 Bot identity, auto-applied

No BotFather trips needed: on every startup the bot sets its **name**,
**description** ("What can this bot do?"), **short description** and the
**"/" command menu** via `setMyName` / `setMyDescription` /
`setMyShortDescription` / `setMyCommands` — localized for default + en + uz +
ru (Telegram limits: 64 / 512 / 120 chars). The panel's *Bot profile* card (or
`/resetprofile`) wipes all localized values and re-applies them from scratch.

## ⚙️ Configuration

All configuration is environment variables (see [`.env.example`](.env.example)):

| Variable | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token |
| `ADMIN_IDS` | ✅ | Comma-separated admin user IDs |
| `SECRET_KEY` | ✅ | Encrypts stored cookies |
| `PUBLIC_BASE_URL` | – | Base URL for the Web App button (auto-derived on HF) |
| `PROXY` | – | Initial proxy pool (admin panel can override live); setting it pins **manual** mode |
| `AUTO_PROXY` | – | Self-maintaining free-proxy worker (default on; `0` disables) |
| `PROXY_REFRESH_MINUTES` | – | Auto-pool rescan interval (default `15`) |
| `PROXY_POOL_SIZE` | – | Healthy proxies to keep (default `12`) |
| `COBALT_ENABLED` | – | Cobalt fast lane for socials (default on) |
| `COBALT_API_URL` | – | Cobalt instance (default `https://api.cobalt.tools`) |
| `COBALT_API_KEY` | – | Api-Key for self-hosted Cobalt, if configured |
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
encryption/validation, media-routing logic, the auto proxy pool (ranking,
cooldowns, scan waves), Cobalt response shapes, Dydki HTML parsing and
query caching, artist artwork matching, InnerTube parsing, and downloader
proxy rotation.

## 🙏 Credits

- Original single-file bot: [ssebastianoo/yt-dlp-telegram](https://github.com/ssebastianoo/yt-dlp-telegram)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [gallery-dl](https://github.com/mikf/gallery-dl) · [aiogram](https://github.com/aiogram/aiogram) · [shazamio](https://github.com/shazamio/ShazamIO) · [Cobalt](https://github.com/imputnet/cobalt) · [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List)

## License

MIT — do your best, credit nicely. Respect the terms of the sites you download
from and the rights of content owners; this tool is for personal use.
