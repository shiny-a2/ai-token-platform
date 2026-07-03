"""Server-side validation of Telegram Mini App initData.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
hash       = HMAC_SHA256(key=secret_key,  msg=data_check_string)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from app.config import settings

MAX_AGE_SECONDS = 24 * 3600


@dataclass
class WebAppUser:
    telegram_id: int
    first_name: str
    username: str | None
    language_code: str | None
    is_admin: bool


def validate_init_data(init_data: str, bot_token: str) -> dict:
    """Return the parsed fields if the signature is valid, else raise ValueError."""
    if not init_data or len(init_data) > 8192:
        raise ValueError("empty_or_oversized")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    given_hash = pairs.pop("hash", None)
    if not given_hash:
        raise ValueError("missing_hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calc_hash, given_hash):
        raise ValueError("bad_signature")

    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date <= 0 or (time.time() - auth_date) > MAX_AGE_SECONDS:
        raise ValueError("stale_auth_date")
    return pairs


async def webapp_user(
    x_init_data: str = Header(default="", alias="X-Init-Data"),
) -> WebAppUser:
    """FastAPI dependency: authenticates every Mini App API request."""
    try:
        fields = validate_init_data(x_init_data, settings.bot_token)
        raw_user = json.loads(fields.get("user", "{}"))
        tg_id = int(raw_user["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="invalid_init_data")
    return WebAppUser(
        telegram_id=tg_id,
        first_name=raw_user.get("first_name", ""),
        username=raw_user.get("username"),
        language_code=raw_user.get("language_code"),
        is_admin=settings.is_admin(tg_id),
    )


async def webapp_admin(
    x_init_data: str = Header(default="", alias="X-Init-Data"),
) -> WebAppUser:
    user = await webapp_user(x_init_data)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="not_admin")
    return user
