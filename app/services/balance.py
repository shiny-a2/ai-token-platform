"""Credit accounting: charge usage, top up from packages, manual adjust."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Package, UserBalance


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InsufficientBalance(Exception):
    def __init__(self, remaining: int, needed: int):
        self.remaining = remaining
        self.needed = needed
        super().__init__(f"need {needed}, have {remaining}")


class CreditExpired(Exception):
    pass


async def _get_balance(db: AsyncSession, user_id: str) -> UserBalance:
    bal = (
        await db.execute(select(UserBalance).where(UserBalance.user_id == user_id))
    ).scalar_one_or_none()
    if bal is None:
        bal = UserBalance(user_id=user_id, total_tokens=0, used_tokens=0)
        db.add(bal)
        await db.flush()
    return bal


async def ensure_can_spend(
    db: AsyncSession, user_id: str, needed: int, *, unrestricted: bool = False
) -> UserBalance:
    bal = await _get_balance(db, user_id)
    if bal.is_expired:
        raise CreditExpired()
    if not unrestricted and bal.remaining < needed:
        raise InsufficientBalance(bal.remaining, needed)
    return bal


async def charge(db: AsyncSession, user_id: str, amount: int) -> UserBalance:
    bal = await _get_balance(db, user_id)
    bal.used_tokens += max(0, amount)
    bal.updated_at = utcnow()
    await db.commit()
    await db.refresh(bal)
    return bal


async def add_package(
    db: AsyncSession, user_id: str, package: Package, *, stack: bool = True
) -> UserBalance:
    """Activate a package: add tokens and set / extend expiry (from now)."""
    bal = await _get_balance(db, user_id)
    new_expiry = utcnow() + timedelta(days=package.validity_days)
    if stack and not bal.is_expired and bal.expires_at:
        bal.total_tokens += package.ai_tokens
        cur = bal.expires_at
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        bal.expires_at = max(cur, new_expiry)
    else:
        # fresh window: expired leftovers are forfeited (30-day validity),
        # non-expired leftovers carry over
        carry = 0 if bal.is_expired else bal.remaining
        bal.total_tokens = carry + package.ai_tokens
        bal.used_tokens = 0
        bal.expires_at = new_expiry
    bal.updated_at = utcnow()
    await db.commit()
    await db.refresh(bal)
    return bal


async def adjust(
    db: AsyncSession,
    user_id: str,
    *,
    delta_total: int = 0,
    set_expiry_days: int | None = None,
) -> UserBalance:
    bal = await _get_balance(db, user_id)
    bal.total_tokens = max(0, bal.total_tokens + delta_total)
    if set_expiry_days is not None:
        bal.expires_at = utcnow() + timedelta(days=set_expiry_days)
    bal.updated_at = utcnow()
    await db.commit()
    await db.refresh(bal)
    return bal
