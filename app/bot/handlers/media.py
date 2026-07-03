"""Image generation, research, vision (photo analysis), files, support."""
from __future__ import annotations

import base64
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select

from app import pricing
from app.bot.handlers.common import resolve_user
from app.bot.keyboards import image_size_kb
from app.bot.states import Flow
from app.config import STORAGE_DIR, settings
from app.db import SessionLocal, new_uuid
from app.i18n import t
from app.models import AIMode, FileAsset
from app.services import balance as balance_svc
from app.services import conversation as conv_svc
from app.services import usage as usage_svc
from app.services import users as users_svc
from app.services.cost_estimator import compute_charge
from app.services.openai_gateway import OpenAIError, chat as openai_chat, generate_image
from app.services.settings_store import get_economics

router = Router()
log = logging.getLogger("bot.media")

ALLOWED_DOC_EXT = {".pdf", ".txt", ".csv", ".jpg", ".jpeg", ".png", ".webp"}
BLOCKED_EXT = {".exe", ".js", ".php", ".sh", ".bat", ".cmd", ".msi", ".dll"}
MAX_FILE_MB = 15


# ---------- research ----------
@router.message(Flow.research_prompt, F.text)
async def on_research(message: Message, state: FSMContext) -> None:
    from app.bot.handlers.chat import process_prompt

    await state.update_data(mode="research")
    await state.set_state(Flow.chatting)
    await process_prompt(message, state, message.text.strip())


# ---------- image ----------
@router.message(Flow.image_prompt, F.text)
async def on_image_prompt(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    await state.update_data(img_prompt=message.text.strip())
    label = "اندازه تصویر را انتخاب کنید:" if lang == "fa" else "Choose image size:"
    await message.answer(label, reply_markup=image_size_kb())


@router.callback_query(F.data.startswith("imgsize:"))
async def on_image_size(cb: CallbackQuery, state: FSMContext) -> None:
    size = cb.data.split(":", 1)[1]
    data = await state.get_data()
    prompt = data.get("img_prompt")
    _, lang = await resolve_user(cb.from_user)
    await cb.answer()
    await state.set_state(Flow.chatting)
    if not prompt:
        await cb.message.answer(t(lang, "image_prompt"))
        return
    await generate_and_send_image(cb.message, state, lang, prompt, size=size)


async def generate_and_send_image(
    message: Message, state: FSMContext, lang: str, prompt: str,
    *, size: str = "1024x1024", quality: str = "medium",
) -> None:
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.chat.id)
        mode = (
            await db.execute(select(AIMode).where(AIMode.code == "image"))
        ).scalar_one_or_none()
        econ = await get_economics(db)
        bal = await users_svc.get_balance(db, user.id)

    if mode is None:
        await message.answer(t(lang, "err_generic"))
        return

    real_usd = pricing.IMAGE_FLAT_USD.get((size, quality), 0.05)
    markup = mode.markup_multiplier or econ.global_markup_multiplier
    charged = pricing.usd_to_ai_tokens(
        real_usd, markup=markup, unit_price_usd=econ.token_unit_price_usd,
        base_credit_cost=mode.base_credit_cost,
        min_charge=econ.min_charge_per_request, max_charge=econ.max_charge_per_request,
    )

    if bal.is_expired:
        await message.answer(t(lang, "err_expired"))
        return
    if not user.unrestricted_usage and bal.remaining < charged:
        await message.answer(t(lang, "err_insufficient", balance=bal.remaining, needed=charged))
        return

    thinking = await message.answer(t(lang, "thinking"))
    async with SessionLocal() as db:
        try:
            img = await generate_image(db, mode.model, prompt, size=size, quality=quality)
        except OpenAIError as exc:
            log.warning("image error: %s", exc)
            await usage_svc.log_usage(
                db, user_id=user.id, conversation_id=None, message_id=None,
                model=mode.model, mode="image", input_tokens=0, output_tokens=0,
                reasoning_tokens=0, api_cost_usd=0.0, charged_ai_tokens=0,
                status="error", error_code=str(exc)[:60],
            )
            await thinking.edit_text(t(lang, "err_openai"))
            return

        try:
            raw = base64.b64decode(img.b64)
        except Exception:
            await thinking.edit_text(t(lang, "err_generic"))
            return

        fname = f"{new_uuid()}.png"
        path = STORAGE_DIR / fname
        path.write_bytes(raw)
        db.add(FileAsset(
            user_id=user.id, original_filename=fname, mime_type="image/png",
            size_bytes=len(raw), storage_path=str(path), kind="output", status="stored",
        ))
        await balance_svc.charge(db, user.id, charged)
        bal = await users_svc.get_balance(db, user.id)
        await usage_svc.log_usage(
            db, user_id=user.id, conversation_id=None, message_id=None,
            model=mode.model, mode="image", input_tokens=0, output_tokens=0,
            reasoning_tokens=0, api_cost_usd=real_usd, charged_ai_tokens=charged, status="ok",
        )

    await thinking.delete()
    caption = t(lang, "charged_footer", charged=charged, remaining=bal.remaining).strip()
    await message.answer_photo(
        BufferedInputFile(raw, filename=fname), caption=caption
    )


# ---------- support ----------
@router.message(Flow.support_message, F.text)
async def on_support(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    uname = f"@{message.from_user.username}" if message.from_user.username else ""
    fwd = (
        f"🆘 پیام پشتیبانی\nاز: {message.from_user.id} {uname}\n\n{message.text}"
    )
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, fwd)
        except Exception:  # noqa: BLE001
            pass
    await state.clear()
    ok = "پیام شما برای پشتیبانی ارسال شد. ✅" if lang == "fa" else "Your message was sent to support. ✅"
    await message.answer(ok)


# ---------- vision / files ----------
@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    photo = message.photo[-1]
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        data = await state.get_data()
        mode = (
            await db.execute(select(AIMode).where(AIMode.code == (data.get("mode") or "")))
        ).scalar_one_or_none()
        econ = await get_economics(db)
        bal = await users_svc.get_balance(db, user.id)
        unrestricted = user.unrestricted_usage

    # download + store
    file = await message.bot.get_file(photo.file_id)
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read()
    fname = f"{new_uuid()}.jpg"
    path = STORAGE_DIR / fname
    path.write_bytes(raw)
    async with SessionLocal() as db:
        db.add(FileAsset(
            user_id=user.id, original_filename=fname, mime_type="image/jpeg",
            size_bytes=len(raw), storage_path=str(path), telegram_file_id=photo.file_id,
            kind="image", status="stored",
        ))
        await db.commit()

    # if a vision-capable mode is active, analyse the image
    if mode is not None and mode.supports_image_input:
        caption = (message.caption or "این تصویر را توصیف کن.").strip()
        data_uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        vmsg = [{
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }]
        thinking = await message.answer(t(lang, "thinking"))
        async with SessionLocal() as db:
            try:
                result = await openai_chat(db, mode, vmsg)
            except OpenAIError:
                await thinking.edit_text(t(lang, "err_openai"))
                return
            charge = compute_charge(
                mode, econ, result.input_tokens, result.output_tokens, result.reasoning_tokens
            )
            await balance_svc.charge(db, user.id, charge.charged_ai_tokens)
            bal = await users_svc.get_balance(db, user.id)
            await usage_svc.log_usage(
                db, user_id=user.id, conversation_id=None, message_id=None,
                model=mode.model, mode=mode.code, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, reasoning_tokens=result.reasoning_tokens,
                api_cost_usd=charge.api_cost_usd, charged_ai_tokens=charge.charged_ai_tokens,
                status="ok",
            )
        footer = t(lang, "charged_footer", charged=charge.charged_ai_tokens, remaining=bal.remaining)
        await thinking.edit_text((result.text or "…") + footer)
        return

    await message.answer(t(lang, "file_stored", size=max(1, len(raw) // 1024)))


@router.message(F.document)
async def on_document(message: Message, state: FSMContext) -> None:
    from app.services.cost_estimator import count_tokens
    from app.services.file_extract import extract_text, extractable

    _, lang = await resolve_user(message.from_user)
    doc = message.document
    name = (doc.file_name or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in BLOCKED_EXT or ext not in ALLOWED_DOC_EXT:
        await message.answer(t(lang, "file_blocked"))
        return
    if (doc.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
        await message.answer(t(lang, "file_too_big"))
        return

    file = await message.bot.get_file(doc.file_id)
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read()
    fname = f"{new_uuid()}{ext}"
    path = STORAGE_DIR / fname
    path.write_bytes(raw)

    text = extract_text(path, doc.file_name or fname) if extractable(name) else None
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        fa = FileAsset(
            user_id=user.id, original_filename=doc.file_name, mime_type=doc.mime_type,
            size_bytes=len(raw), storage_path=str(path), telegram_file_id=doc.file_id,
            kind="document", status="stored", extracted_text=text,
        )
        db.add(fa)
        await db.commit()
        await db.refresh(fa)

    if text:
        tokens = count_tokens(text)
        await state.update_data(file_id=fa.id, file_name=doc.file_name)
        note = (
            f"📎 فایل «{doc.file_name}» پیوست شد (حدود {tokens:,} توکن).\n"
            "سوال خود را دربارهٔ آن بپرسید — هزینهٔ فایل در تخمین پیام بعدی لحاظ می‌شود.\n"
            "برای جدا کردن فایل، چت جدید بزنید."
            if lang == "fa" else
            f"📎 “{doc.file_name}” attached (~{tokens:,} tokens). Ask about it; "
            "its cost is included in the next estimate."
        )
        await message.answer(note)
        # a caption acts as the first question about the file
        if message.caption:
            from app.bot.handlers.chat import process_prompt

            await process_prompt(message, state, message.caption.strip())
    else:
        await message.answer(t(lang, "file_stored", size=max(1, len(raw) // 1024)))
