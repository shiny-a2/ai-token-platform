"""Async database engine + session factory."""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return uuid.uuid4().hex


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    # Import models so metadata is populated before create_all.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_mini_migrations(conn)


async def _run_mini_migrations(conn) -> None:
    """Additive column migrations for SQLite (create_all never ALTERs)."""
    from sqlalchemy import text

    wanted = {
        "users": {
            "default_mode": "ALTER TABLE users ADD COLUMN default_mode VARCHAR(64)",
            "allowed_modes": "ALTER TABLE users ADD COLUMN allowed_modes JSON",
            "effort_overrides": "ALTER TABLE users ADD COLUMN effort_overrides JSON",
        },
        "packages": {
            "price_toman": "ALTER TABLE packages ADD COLUMN price_toman INTEGER",
        },
        "files": {
            "extracted_text": "ALTER TABLE files ADD COLUMN extracted_text TEXT",
        },
    }
    for table, columns in wanted.items():
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        existing = {r[1] for r in rows}
        for col, ddl in columns.items():
            if col not in existing:
                await conn.execute(text(ddl))
