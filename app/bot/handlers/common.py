"""Shared helpers for bot handlers."""
from __future__ import annotations

from aiogram.types import CallbackQuery, Message, User as TgUser

from app.bot.keyboards import main_menu
from app.db import SessionLocal
from app.i18n import t
from app.models import User
from app.services import users as users_svc


async def resolve_user(tg: TgUser) -> tuple[User, str]:
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(
            db,
            tg.id,
            username=tg.username,
            first_name=tg.first_name,
            last_name=tg.last_name,
        )
        return user, user.language


async def send_main_menu(message: Message, lang: str, text: str | None = None) -> None:
    await message.answer(
        text or t(lang, "main_menu_title"),
        reply_markup=main_menu(lang),
    )
