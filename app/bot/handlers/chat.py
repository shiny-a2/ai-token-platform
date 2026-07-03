"""Chat pipeline: mode selection, cost estimate/confirm, send via chat_service."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import resolve_user
from app.bot.keyboards import confirm_kb
from app.bot.states import Flow
from app.db import SessionLocal
from app.i18n import t
from app.services import chat_service
from app.services import users as users_svc

router = Router()
log = logging.getLogger("bot.chat")


async def _effective_mode_code(state: FSMContext, user) -> str:
    """FSM state first, then the user's persisted default, then fast_chat."""
    data = await state.get_data()
    return data.get("mode") or user.default_mode or "fast_chat"


@router.callback_query(F.data.startswith("mode:"))
async def on_mode(cb: CallbackQuery, state: FSMContext) -> None:
    code = cb.data.split(":", 1)[1]
    async with SessionLocal() as db:
        mode = await chat_service.load_mode(db, code)
        user = await users_svc.get_or_create(db, cb.from_user.id)
        user.default_mode = mode.code if mode else code
        await db.commit()
        lang = user.language
        name = (mode.fa_name if lang == "fa" else mode.en_name) if mode else code
    await state.update_data(mode=code)
    await state.set_state(Flow.chatting)
    await cb.answer()
    await cb.message.answer(t(lang, "mode_selected", name=name))


@router.callback_query(F.data.startswith("conv:"))
async def on_open_conversation(cb: CallbackQuery, state: FSMContext) -> None:
    conv_id = cb.data.split(":", 1)[1]
    async with SessionLocal() as db:
        from app.services import conversation as conv_svc

        conv = await conv_svc.get_conversation(db, conv_id)
        user = await users_svc.get_or_create(db, cb.from_user.id)
        lang = user.language
        if not conv or conv.user_id != user.id:
            await cb.answer()
            return
        mode = conv.current_mode or user.default_mode or "fast_chat"
    await state.set_state(Flow.chatting)
    await state.update_data(conv_id=conv_id, mode=mode)
    await cb.answer()
    await cb.message.answer(t(lang, "new_chat_started", mode=mode))


# ---- confirm flow ----
@router.callback_query(F.data == "send:no")
async def on_send_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    _, lang = await resolve_user(cb.from_user)
    await state.set_state(Flow.chatting)
    await state.update_data(pending_text=None, pending_cap=None)
    await cb.answer()
    await cb.message.answer(t(lang, "cancelled"))


@router.callback_query(F.data == "send:yes")
async def on_send_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("pending_text")
    cap = data.get("pending_cap")
    await state.update_data(pending_text=None, pending_cap=None)
    await state.set_state(Flow.chatting)
    await cb.answer()
    if not text:
        return
    await _run_chat(cb.message, cb.from_user, state, text, cap=cap)


# ---- free text ----
@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext) -> None:
    await process_prompt(message, state, message.text.strip())


async def _attached_file(db, state: FSMContext, user_id: str):
    """Return (file_text, file_name) for the conversation's attachment, if any."""
    from app.models import FileAsset

    data = await state.get_data()
    file_id = data.get("file_id")
    if not file_id:
        return None, None
    fa = await db.get(FileAsset, file_id)
    if fa is None or fa.user_id != user_id or not fa.extracted_text:
        return None, None
    return fa.extracted_text, (data.get("file_name") or fa.original_filename)


async def process_prompt(message: Message, state: FSMContext, user_text: str) -> None:
    """Estimate cost, optionally ask for confirmation, then run the chat."""
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        lang = user.language
        mode_code = await _effective_mode_code(state, user)
        mode = await chat_service.load_mode(db, mode_code)
        if mode is None:
            await message.answer(t(lang, "err_generic"))
            return
        file_text, _ = await _attached_file(db, state, user.id)
        est = await chat_service.estimate_turn(db, user, mode, user_text,
                                               file_text=file_text)
        unrestricted = user.unrestricted_usage
        supports_image_out = mode.supports_image_output

    # image mode: delegate to image generator
    if supports_image_out:
        from app.bot.handlers.media import generate_and_send_image

        await generate_and_send_image(message, state, lang, user_text)
        return

    if not unrestricted and est.balance < est.min_credits:
        await message.answer(
            t(lang, "err_insufficient", balance=est.balance, needed=est.min_credits)
        )
        return

    if est.requires_confirmation:
        await state.update_data(pending_text=user_text, pending_cap=est.max_credits,
                                mode=mode.code)
        await state.set_state(Flow.confirming_send)
        name = mode.fa_name if lang == "fa" else mode.en_name
        await message.answer(
            t(lang, "estimate_block", mode=name, in_tok=est.in_tokens,
              min=est.min_credits, max=est.max_credits, balance=est.balance),
            reply_markup=confirm_kb(lang),
        )
        return

    await _run_chat(message, message.from_user, state, user_text,
                    cap=est.max_credits if not unrestricted else None)


async def _run_chat(message: Message, tg_user, state: FSMContext, user_text: str,
                    *, cap: int | None) -> None:
    lang = "fa"
    thinking = await message.answer(t(lang, "thinking"))
    try:
        async with SessionLocal() as db:
            user = await users_svc.get_or_create(db, tg_user.id)
            lang = user.language
            mode_code = await _effective_mode_code(state, user)
            mode = await chat_service.load_mode(db, mode_code)
            data = await state.get_data()
            file_text, file_name = await _attached_file(db, state, user.id)
            result = await chat_service.run_turn(
                db, user, mode, user_text, conv_id=data.get("conv_id"), cap=cap,
                file_text=file_text, file_name=file_name,
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("chat failed: %s", exc)
        await thinking.edit_text(t(lang, "err_generic"))
        return

    if not result.ok:
        if result.error == "expired":
            await thinking.edit_text(t(lang, "err_expired"))
        elif result.error == "insufficient":
            await thinking.edit_text(
                t(lang, "err_insufficient", balance=result.balance, needed=result.needed)
            )
        else:
            await thinking.edit_text(t(lang, "err_openai"))
        return

    await state.update_data(conv_id=result.conv_id)
    footer = t(lang, "charged_footer", charged=result.charged,
               remaining=result.remaining)
    full = result.reply + footer
    if len(full) > 4000:
        # long answers are DELIVERED AS A FILE (telegram cap ~4096 chars)
        from aiogram.types import BufferedInputFile

        doc = BufferedInputFile(result.reply.encode("utf-8"), filename="پاسخ.md")
        preview = result.reply[:900] + "…"
        await thinking.edit_text(preview + footer)
        await message.answer_document(
            doc,
            caption="📄 متن کامل پاسخ" if lang == "fa" else "📄 Full answer",
        )
    else:
        await thinking.edit_text(full)
