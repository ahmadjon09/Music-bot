"""Secrets handling: cookie encryption + Telegram Web App authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from cryptography.fernet import Fernet, InvalidToken

# ── Cookie encryption (Fernet, key derived from SECRET_KEY) ─────────────────

def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(secret_key: str, plain: str) -> str:
    return _fernet(secret_key).encrypt(plain.encode()).decode()


def decrypt_text(secret_key: str, token: str) -> str | None:
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None  # wrong SECRET_KEY or corrupted blob — fail soft, not loud


# ── Cookies.txt validation ───────────────────────────────────────────────────

MAX_COOKIE_BYTES = 1_000_000  # 1 MB is plenty; bigger files are usually accidents


def validate_cookies(content: str) -> dict:
    """Validate Netscape cookies.txt content. Returns a small report dict."""
    if len(content.encode()) > MAX_COOKIE_BYTES:
        return {"ok": False, "error": "File too large (max 1 MB)"}
    domains: dict[str, int] = {}
    total = 0
    for line in content.splitlines():
        line = line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        clean = line.removeprefix("#HttpOnly_")
        fields = clean.split("\t")
        if len(fields) < 7:
            continue
        domain = fields[0].lstrip(".").lower()
        if domain:
            domains[domain] = domains.get(domain, 0) + 1
            total += 1
    if total == 0:
        return {"ok": False, "error": "No valid cookies found (expected Netscape format)"}
    return {"ok": True, "total": total, "domains": dict(sorted(domains.items()))}


# ── Telegram Mini App (Web App) initData validation ──────────────────────────
# Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

_MAX_INITDATA_AGE = 24 * 3600  # reject auth payloads older than a day


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Return the parsed payload when the HMAC signature checks out, else None."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):  # constant-time, no leaks
        return None

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if time.time() - auth_date > _MAX_INITDATA_AGE:
        return None

    user_raw = pairs.get("user")
    if user_raw:
        try:
            pairs["user_parsed"] = json.loads(user_raw)
        except (ValueError, TypeError):
            return None
    return pairs


def init_data_user_id(init_data: str, bot_token: str) -> int | None:
    payload = validate_init_data(init_data, bot_token)
    if not payload:
        return None
    user = payload.get("user_parsed") or {}
    uid = user.get("id")
    return int(uid) if isinstance(uid, int) else None
