"""User + balance provisioning."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, UserBalance
from app.services.balance import utcnow


async def get_by_telegram_id(db: AsyncSession, tg_id: int) -> User | None:
    return (
        await db.execute(select(User).where(User.telegram_user_id == tg_id))
    ).scalar_one_or_none()


async def get_or_create(
    db: AsyncSession,
    tg_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    user = await get_by_telegram_id(db, tg_id)
    if user is None:
        user = User(
            telegram_user_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language=settings.default_language,
            role="admin" if settings.is_admin(tg_id) else "user",
        )
        db.add(user)
        await db.flush()
        db.add(UserBalance(user_id=user.id, total_tokens=0, used_tokens=0))
        await db.commit()
        await db.refresh(user)
    else:
        changed = False
        if username and user.username != username:
            user.username, changed = username, True
        if first_name and user.first_name != first_name:
            user.first_name, changed = first_name, True
        if settings.is_admin(tg_id) and user.role != "admin":
            user.role, changed = "admin", True
        # throttle the last_seen write: one DB commit per 5 minutes per user,
        # not one per API call (this is on the hot path of every request)
        now = utcnow()
        last = user.last_seen_at
        if last is not None and last.tzinfo is None:
            from datetime import timezone as _tz

            last = last.replace(tzinfo=_tz.utc)
        stale = last is None or (now - last).total_seconds() > 300
        if changed or stale:
            user.last_seen_at = now
            await db.commit()
            if changed:
                await db.refresh(user)
    return user


async def get_balance(db: AsyncSession, user_id: str) -> UserBalance:
    bal = (
        await db.execute(select(UserBalance).where(UserBalance.user_id == user_id))
    ).scalar_one_or_none()
    if bal is None:
        bal = UserBalance(user_id=user_id, total_tokens=0, used_tokens=0)
        db.add(bal)
        await db.commit()
        await db.refresh(bal)
    return bal
