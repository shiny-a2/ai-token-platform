"""Recharge flow: choose package, show payment info, submit receipt."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.handlers.common import resolve_user
from app.bot.keyboards import _num, price_label, receipt_review_kb
from app.bot.states import Flow
from app.config import STORAGE_DIR, settings
from app.db import SessionLocal, new_uuid
from app.i18n import t
from app.models import FileAsset, Package
from app.services import payments as pay_svc
from app.services import users as users_svc

router = Router()
log = logging.getLogger("bot.recharge")


@router.callback_query(F.data.startswith("pkg:"))
async def on_package(cb: CallbackQuery, state: FSMContext) -> None:
    pkg_id = cb.data.split(":", 1)[1]
    _, lang = await resolve_user(cb.from_user)
    async with SessionLocal() as db:
        package = await db.get(Package, pkg_id)
        methods = await pay_svc.list_active_methods(db)
        methods_text = pay_svc.format_methods(methods) if methods else ""
    if package is None:
        await cb.answer()
        return
    await cb.answer()
    if not methods:
        await cb.message.answer(t(lang, "no_payment_methods"))
        return
    await state.set_state(Flow.awaiting_receipt)
    await state.update_data(package_id=pkg_id)
    await cb.message.answer(
        t(lang, "payment_instructions", name=package.name,
          price=price_label(package, lang), methods=methods_text)
    )


async def _notify_admins(message: Message, user_disp: str, package: Package | None,
                         receipt_id: str, photo_file_id: str | None) -> None:
    amount = _num(package.price_usd) if package else "?"
    pkg_name = package.name if package else "—"
    caption = t("fa", "new_receipt_admin", user=user_disp, package=pkg_name, amount=amount)
    for admin_id in settings.admin_ids:
        try:
            if photo_file_id:
                await message.bot.send_photo(
                    admin_id, photo_file_id, caption=caption,
                    reply_markup=receipt_review_kb(receipt_id),
                )
            else:
                await message.bot.send_message(
                    admin_id, caption, reply_markup=receipt_review_kb(receipt_id)
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("notify admin %s failed: %s", admin_id, exc)


@router.message(Flow.awaiting_receipt, F.photo)
async def on_receipt_photo(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    photo = message.photo[-1]
    data = await state.get_data()
    pkg_id = data.get("package_id")

    # store the receipt image privately
    file = await message.bot.get_file(photo.file_id)
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read()
    fname = f"receipt_{new_uuid()}.jpg"
    path = STORAGE_DIR / fname
    path.write_bytes(raw)

    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        package = await db.get(Package, pkg_id) if pkg_id else None
        fa = FileAsset(
            user_id=user.id, original_filename=fname, mime_type="image/jpeg",
            size_bytes=len(raw), storage_path=str(path), telegram_file_id=photo.file_id,
            kind="receipt", status="stored",
        )
        db.add(fa)
        await db.flush()
        receipt = await pay_svc.create_receipt(
            db, user_id=user.id, package=package, telegram_file_id=photo.file_id, method="manual"
        )
        receipt.receipt_file_id = fa.id
        await db.commit()
        user_disp = f"{user.first_name or ''} ({user.telegram_user_id})"

    await state.clear()
    await message.answer(t(lang, "receipt_received"))
    await _notify_admins(message, user_disp, package, receipt.id, photo.file_id)


@router.message(Flow.awaiting_receipt, F.text)
async def on_receipt_txid(message: Message, state: FSMContext) -> None:
    _, lang = await resolve_user(message.from_user)
    data = await state.get_data()
    pkg_id = data.get("package_id")
    txid = message.text.strip()
    checking = await message.answer(
        "🔎 در حال استعلام خودکار تراکنش…" if lang == "fa" else "🔎 Verifying transaction…"
    )
    async with SessionLocal() as db:
        user = await users_svc.get_or_create(db, message.from_user.id)
        package = await db.get(Package, pkg_id) if pkg_id else None
        receipt = await pay_svc.create_receipt(
            db, user_id=user.id, package=package, txid=txid, method="crypto"
        )
        status, result = await pay_svc.process_txid_receipt(db, receipt, package)
        user_disp = f"{user.first_name or ''} ({user.telegram_user_id})"
        added = package.ai_tokens if package else 0
    await state.clear()

    if status == "approved":
        await checking.edit_text(
            t(lang, "receipt_approved_user", tokens=added)
            + (f"\n({result.network} — {result.amount_usd:.2f}$)" if result else "")
        )
        note = (f"✅ رسید خودکار تایید شد\nکاربر: {user_disp}\n"
                f"پکیج: {package.name if package else '—'}\n"
                f"{result.network} — {result.amount_usd:.2f}$" if result else "")
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, note)
            except Exception:  # noqa: BLE001
                pass
    else:
        extra = ""
        if result and result.note:
            extra = ("\nنتیجه استعلام: " + result.note) if lang == "fa" else ""
        await checking.edit_text(t(lang, "receipt_received") + extra)
        await _notify_admins(message, user_disp, package, receipt.id, None)
