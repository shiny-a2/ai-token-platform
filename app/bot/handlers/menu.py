"""Main-menu button dispatch (works in fa and en, any state)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from app.bot.handlers.common import resolve_user
from app.bot.keyboards import main_menu, match_menu, modes_kb, packages_kb
from app.bot.states import Flow
from app.db import SessionLocal
from app.i18n import t
from app.models import AIMode, Conversation
from app.services import payments as pay_svc
from app.services import users as users_svc

router = Router()


def is_menu(message: Message) -> bool:
    return match_menu(message.text or "") is not None


async def _active_modes(db) -> list[AIMode]:
    rows = (
        await db.execute(
            select(AIMode).where(AIMode.is_active.is_(True)).order_by(AIMode.sort_order)
        )
    ).scalars().all()
    return list(rows)


@router.message(is_menu)
async def on_menu(message: Message, state: FSMContext) -> None:
    action = match_menu(message.text or "")
    _, lang = await resolve_user(message.from_user)

    if action == "new_chat":
        data = await state.get_data()
        mode = data.get("mode") or "fast_chat"
        await state.set_state(Flow.chatting)
        await state.update_data(mode=mode, conv_id=None)
        await message.answer(t(lang, "new_chat_started", mode=mode))

    elif action == "select_mode":
        async with SessionLocal() as db:
            modes = await _active_modes(db)
        await message.answer(t(lang, "choose_mode_title"), reply_markup=modes_kb(modes, lang))

    elif action == "usage":
        await _show_usage(message, lang)

    elif action == "my_chats":
        await _show_chats(message, lang)

    elif action == "image":
        await state.set_state(Flow.image_prompt)
        await message.answer(t(lang, "image_prompt"))

    elif action == "research":
        await state.set_state(Flow.research_prompt)
        await message.answer(t(lang, "research_prompt"))

    elif action == "files":
        await message.answer(t(lang, "send_file_prompt"))

    elif action == "recharge":
        async with SessionLocal() as db:
            packages = await pay_svc.list_active_packages(db)
        if not packages:
            await message.answer(t(lang, "no_packages"))
            return
        await message.answer(
            t(lang, "choose_package"), reply_markup=packages_kb(packages, lang)
        )

    elif action == "settings":
        await state.clear()
        await _show_settings(message, lang)

    elif action == "support":
        await state.set_state(Flow.support_message)
        await message.answer(t(lang, "support_text"))

    elif action == "categories":
        await message.answer("📁 " + t(lang, "main_menu_title"), reply_markup=main_menu(lang))


async def _show_usage(message: Message, lang: str) -> None:
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        bal = await users_svc.get_balance(db, user.id)
    expires = t(lang, "no_expiry")
    if bal.expires_at:
        expires = bal.expires_at.strftime("%Y-%m-%d")
    await message.answer(
        t(
            lang, "usage_report",
            total=bal.total_tokens, used=bal.used_tokens,
            remaining=bal.remaining, expires=expires,
        )
    )


async def _show_chats(message: Message, lang: str) -> None:
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        rows = (
            await db.execute(
                select(Conversation)
                .where(Conversation.user_id == user.id, Conversation.is_archived.is_(False))
                .order_by(Conversation.updated_at.desc())
                .limit(15)
            )
        ).scalars().all()
    if not rows:
        await message.answer(t(lang, "no_active_chat"))
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=(c.title or "…")[:40], callback_data=f"conv:{c.id}")]
            for c in rows
        ]
    )
    await message.answer(t(lang, "menu_my_chats"), reply_markup=kb)


async def _show_settings(message: Message, lang: str) -> None:
    from app.config import settings as app_settings

    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        unrestricted = user.unrestricted_usage
    rows = [[InlineKeyboardButton(text=t(lang, "settings_language"), callback_data="set:lang")]]
    if app_settings.is_admin(message.from_user.id):  # admin-only billing toggle
        toggle_key = "settings_unrestricted_on" if unrestricted else "settings_unrestricted_off"
        rows.append([InlineKeyboardButton(text=t(lang, toggle_key), callback_data="set:unrestricted")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(t(lang, "settings_title"), reply_markup=kb)
