"""Admin Telegram shortcuts: /admin, receipt approve/reject, quick reports."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards import admin_kb, receipt_review_kb
from app.config import settings
from app.db import SessionLocal
from app.i18n import t
from app.models import PaymentReceipt, User
from app.services import payments as pay_svc
from app.services import usage as usage_svc

router = Router()
log = logging.getLogger("bot.admin")


def _is_admin(tg_id: int) -> bool:
    return settings.is_admin(tg_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    lang = "fa"
    if not _is_admin(message.from_user.id):
        await message.answer(t(lang, "not_admin"))
        return
    try:
        await message.answer(
            t(lang, "admin_panel"),
            reply_markup=admin_kb(lang, settings.dashboard_url),
        )
    except Exception:  # noqa: BLE001 — e.g. BUTTON_URL_INVALID on local URLs
        txt = t(lang, "admin_panel") + f"\n🖥 {settings.dashboard_url}"
        await message.answer(txt)


@router.callback_query(F.data == "admin:receipts")
async def on_pending_receipts(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer(t("fa", "not_admin"), show_alert=True)
        return
    await cb.answer()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(PaymentReceipt)
                .where(PaymentReceipt.status == "pending")
                .order_by(PaymentReceipt.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
    if not rows:
        await cb.message.answer("رسید در انتظاری وجود ندارد. ✅")
        return
    for r in rows:
        txt = f"🧾 رسید {r.id[:8]}\nمبلغ: {r.amount_usd or '?'}$\nروش: {r.method or '-'}"
        if r.txid:
            txt += f"\nTxID: {r.txid}"
        if r.telegram_file_id:
            await cb.message.answer_photo(
                r.telegram_file_id, caption=txt, reply_markup=receipt_review_kb(r.id)
            )
        else:
            await cb.message.answer(txt, reply_markup=receipt_review_kb(r.id))


@router.callback_query(F.data == "admin:today")
async def on_today(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer(t("fa", "not_admin"), show_alert=True)
        return
    await cb.answer()
    async with SessionLocal() as db:
        k = await usage_svc.dashboard_kpis(db)
    txt = (
        "📈 گزارش امروز\n\n"
        f"هزینه API امروز: ${k['today_cost']}\n"
        f"هزینه API ۳۰ روز: ${k['month_cost']}\n"
        f"درآمد کل: ${k['revenue']}\n"
        f"سود تقریبی: ${k['profit']}\n"
        f"کاربران فعال: {k['active_users']}\n"
        f"رسیدهای در انتظار: {k['pending_receipts']}\n"
        f"درخواست‌های ناموفق: {k['failed_requests']}"
    )
    await cb.message.answer(txt)


@router.callback_query(F.data.startswith("rcpt:"))
async def on_review(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer(t("fa", "not_admin"), show_alert=True)
        return
    _, action, receipt_id = cb.data.split(":", 2)
    async with SessionLocal() as db:
        admin_user = (
            await db.execute(
                select(User).where(User.telegram_user_id == cb.from_user.id)
            )
        ).scalar_one_or_none()
        admin_uid = admin_user.id if admin_user else None
        try:
            if action == "ok":
                receipt, added = await pay_svc.approve_receipt(db, receipt_id, admin_uid)
                target = await db.get(User, receipt.user_id)
                result_msg = f"✅ تایید شد ({added} اعتبار)"
                notify = t(target.language if target else "fa",
                           "receipt_approved_user", tokens=added)
            else:
                receipt = await pay_svc.reject_receipt(db, receipt_id, admin_uid, note="")
                target = await db.get(User, receipt.user_id)
                result_msg = "❌ رد شد"
                notify = t(target.language if target else "fa",
                           "receipt_rejected_user", note="")
        except ValueError:
            await cb.answer("قبلاً بررسی شده یا یافت نشد.", show_alert=True)
            return
        target_tg = target.telegram_user_id if target else None

    await cb.answer(result_msg, show_alert=True)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    if target_tg:
        try:
            await cb.bot.send_message(target_tg, notify)
        except Exception as exc:  # noqa: BLE001
            log.warning("notify user failed: %s", exc)
