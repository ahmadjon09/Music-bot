"""Environment-driven configuration.

Everything is read from environment variables (Hugging Face *Secrets* in
production, a local ``.env`` file in development). No secrets ever live in
the repository — that would be a funny commit to explain.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — one less dependency, zero magic."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT_DIR / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _id_list(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            ids.append(int(chunk))
    return ids


def resolve_ffmpeg() -> str | None:
    """Prefer a system ffmpeg; fall back to the static wheel binary."""
    if exe := shutil.which("ffmpeg"):
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — ffmpeg is optional until media work starts
        return None


def resolve_js_runtime() -> dict | None:
    """yt-dlp needs a JS runtime for some YouTube challenges (EJS)."""
    for name in ("node", "deno"):
        if path := shutil.which(name):
            return {name: {"path": path}}
    return None


def derive_public_url() -> str:
    """Best-effort public URL of this deployment (for the Web App button)."""
    if url := os.getenv("PUBLIC_BASE_URL", "").strip():
        return url.rstrip("/")
    # Hugging Face Spaces expose SPACE_ID as "user/space-name".
    space_id = os.getenv("SPACE_ID", "").strip()
    if "/" in space_id:
        user, name = space_id.split("/", 1)
        return f"https://{user}-{name}.hf.space".lower()
    if host := os.getenv("SPACE_HOST", "").strip():
        return f"https://{host}"
    return ""


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    admin_ids: frozenset[int] = field(
        default_factory=lambda: frozenset(_id_list(os.getenv("ADMIN_IDS", "")))
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("SECRET_KEY", "dev-secret-change-me").strip()
    )
    public_base_url: str = field(default_factory=derive_public_url)
    initial_proxy: str = field(
        default_factory=lambda: (os.getenv("PROXY", "") or os.getenv("WARP_PROXY", "")).strip())

    # Storage — on HF Spaces the repo dir is writable; DATA_DIR lets Docker
    # users point at a mounted volume instead.
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT_DIR / "data")).resolve()
    )

    # Behaviour limits (Telegram bots can upload ~50 MB via the public API).
    max_filesize: int = field(default_factory=lambda: _int_env("MAX_FILESIZE_MB", 49) * 1024 * 1024)
    max_global_downloads: int = field(default_factory=lambda: max(1, _int_env("MAX_GLOBAL_DOWNLOADS", 3)))
    max_user_downloads: int = field(default_factory=lambda: max(1, _int_env("MAX_USER_DOWNLOADS", 1)))
    search_max_duration: int = field(default_factory=lambda: _int_env("SEARCH_MAX_DURATION", 600))
    search_results: int = 30          # fetched & filtered, shown 10 per page
    search_page_size: int = 10
    carousel_limit: int = 20          # hard cap so one post can't nuke the RAM

    # Cobalt (Instagram/TikTok/X/… fast lane). Public instance by default;
    # point COBALT_API_URL at your own instance for heavier use.
    cobalt_enabled: bool = field(default_factory=lambda: os.getenv("COBALT_ENABLED", "1") != "0")
    cobalt_api_url: str = field(
        default_factory=lambda: os.getenv("COBALT_API_URL", "https://api.cobalt.tools").strip().rstrip("/"))
    cobalt_api_key: str = field(default_factory=lambda: os.getenv("COBALT_API_KEY", "").strip())

    # Self-maintaining free-proxy pool (TheSpeedX lists → YouTube-verified).
    auto_proxy: bool = field(default_factory=lambda: os.getenv("AUTO_PROXY", "1") != "0")
    proxy_refresh_minutes: int = field(
        default_factory=lambda: max(5, _int_env("PROXY_REFRESH_MINUTES", 15)))
    proxy_pool_size: int = field(default_factory=lambda: max(3, _int_env("PROXY_POOL_SIZE", 12)))

    debug_admin: bool = field(default_factory=lambda: os.getenv("DEBUG_ADMIN", "") == "1")
    port: int = field(default_factory=lambda: _int_env("PORT", 7860))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.db"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def token_looks_valid(self) -> bool:
        # Telegram tokens look like "123456789:AA...." — good enough a sniff test.
        head, sep, tail = self.bot_token.partition(":")
        return bool(sep and head.isdigit() and len(tail) >= 20 and "replace" not in tail)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
