"""Runtime system settings stored in DB, overriding .env defaults.

Economics (unit price, markup, charge caps) live here so the admin can
change them from the panel without a redeploy.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt, encrypt
from app.models import SystemSetting

ECON_KEYS = {
    "token_unit_price_usd": float,
    "global_markup_multiplier": float,
    "min_charge_per_request": int,
    "max_charge_per_request": int,
}


@dataclass
class Economics:
    token_unit_price_usd: float
    global_markup_multiplier: float
    min_charge_per_request: int
    max_charge_per_request: int


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = await db.get(SystemSetting, key)
    if row is None:
        return default
    if row.is_encrypted:
        return decrypt(row.value or "")
    return row.value


async def set_setting(
    db: AsyncSession, key: str, value: str, *, encrypted: bool = False
) -> None:
    row = await db.get(SystemSetting, key)
    stored = encrypt(value) if encrypted else value
    if row is None:
        row = SystemSetting(key=key, value=stored, is_encrypted=encrypted)
        db.add(row)
    else:
        row.value = stored
        row.is_encrypted = encrypted
    await db.commit()


async def all_settings(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    out: dict[str, str] = {}
    for r in rows:
        out[r.key] = decrypt(r.value or "") if r.is_encrypted else (r.value or "")
    return out


async def get_economics(db: AsyncSession) -> Economics:
    async def val(key, caster, fallback):
        raw = await get_setting(db, key)
        if raw is None or raw == "":
            return fallback
        try:
            return caster(raw)
        except (TypeError, ValueError):
            return fallback

    return Economics(
        token_unit_price_usd=await val(
            "token_unit_price_usd", float, settings.token_unit_price_usd
        ),
        global_markup_multiplier=await val(
            "global_markup_multiplier", float, settings.global_markup_multiplier
        ),
        min_charge_per_request=await val(
            "min_charge_per_request", int, settings.min_charge_per_request
        ),
        max_charge_per_request=await val(
            "max_charge_per_request", int, settings.max_charge_per_request
        ),
    )
