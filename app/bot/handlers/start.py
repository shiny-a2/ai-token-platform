"""/start, language selection, privacy acceptance, settings callbacks."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import resolve_user, send_main_menu
from app.bot.keyboards import language_kb, main_menu
from app.db import SessionLocal
from app.i18n import t
from app.services import users as users_svc

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user, lang = await resolve_user(message.from_user)
    await state.clear()
    if not user.accepted_privacy:
        await message.answer(t(lang, "choose_language"), reply_markup=language_kb())
        return
    await message.answer(
        t(lang, "welcome", name=user.first_name or ""),
        reply_markup=main_menu(lang),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    await state.clear()
    await send_main_menu(message, lang)


@router.callback_query(F.data.startswith("lang:"))
async def on_language(cb: CallbackQuery, state: FSMContext) -> None:
    lang = cb.data.split(":", 1)[1]
    lang = lang if lang in ("fa", "en") else "fa"
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, cb.from_user.id)
        user.language = lang
        user.accepted_privacy = True  # onboarding flag; no separate notice step
        await db.commit()
        name = user.first_name or ""
    await cb.answer(t(lang, "lang_set"))
    await state.clear()
    await cb.message.answer(t(lang, "welcome", name=name), reply_markup=main_menu(lang))


@router.callback_query(F.data == "set:lang")
async def settings_language(cb: CallbackQuery) -> None:
    _, lang = await resolve_user(cb.from_user)
    await cb.answer()
    await cb.message.answer(t(lang, "choose_language"), reply_markup=language_kb())


@router.callback_query(F.data == "set:unrestricted")
async def settings_unrestricted(cb: CallbackQuery) -> None:
    from app.config import settings

    # billing kill-switch — admin-only privilege
    if not settings.is_admin(cb.from_user.id):
        await cb.answer(t("fa", "not_admin"), show_alert=True)
        return
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, cb.from_user.id)
        user.unrestricted_usage = not user.unrestricted_usage
        await db.commit()
        lang, on = user.language, user.unrestricted_usage
    await cb.answer(
        t(lang, "settings_unrestricted_on" if on else "settings_unrestricted_off"),
        show_alert=True,
    )
