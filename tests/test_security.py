import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from src.security import (
    decrypt_text,
    encrypt_text,
    init_data_user_id,
    validate_cookies,
)

TOKEN = "123456:AA-test-token-for-unit-tests-only"


def make_init_data(user_id: int, bot_token: str = TOKEN, auth_date: int | None = None) -> str:
    pairs = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": "Test"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_valid_init_data():
    assert init_data_user_id(make_init_data(777), TOKEN) == 777


def test_tampered_init_data_rejected():
    data = make_init_data(777).replace("777", "999")
    assert init_data_user_id(data, TOKEN) is None


def test_expired_init_data_rejected():
    old = int(time.time()) - 25 * 3600
    assert init_data_user_id(make_init_data(777, auth_date=old), TOKEN) is None


def test_encrypt_roundtrip():
    blob = encrypt_text("secret-key", "cookie-monster")
    assert blob != "cookie-monster"
    assert decrypt_text("secret-key", blob) == "cookie-monster"
    assert decrypt_text("wrong-key", blob) is None


def test_validate_cookies_counts_domains():
    sample = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tHSID\txyz\n"
        ".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tqwe\n"
    )
    report = validate_cookies(sample)
    assert report["ok"] is True
    assert report["total"] == 3
    assert report["domains"] == {"instagram.com": 1, "youtube.com": 2}


def test_validate_cookies_rejects_garbage():
    assert validate_cookies("hello world")["ok"] is False
