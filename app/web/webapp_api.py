"""Mini App API — every endpoint is authenticated with Telegram initData."""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import pricing
from app.config import STORAGE_DIR, settings
from app.crypto import decrypt
from app.db import get_session, new_uuid
from app.i18n import t
from app.models import (
    AIMode,
    Conversation,
    FileAsset,
    Message,
    Package,
    PaymentReceipt,
    UsageLog,
    User,
    UserBalance,
)
from app.services import balance as balance_svc
from app.services import chat_service
from app.services import payments as pay_svc
from app.services import usage as usage_svc
from app.services import users as users_svc
from app.services.settings_store import get_economics, get_setting
from app.web.webapp_auth import WebAppUser, webapp_admin, webapp_user

router = APIRouter(prefix="/api/webapp")
log = logging.getLogger("webapp_api")

MAX_RECEIPT_MB = 10

# ---- tiny in-memory per-user rate limiter (single-process app) ----
_rate_buckets: dict[tuple[int, str], list[float]] = {}


def _rate_limit(tg_id: int, action: str, limit: int, window_s: int) -> None:
    import time as _time

    now = _time.monotonic()
    key = (tg_id, action)
    bucket = [t_ for t_ in _rate_buckets.get(key, []) if now - t_ < window_s]
    if len(bucket) >= limit:
        raise HTTPException(429, "rate_limited")
    bucket.append(now)
    _rate_buckets[key] = bucket


def _sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _db_user(db: AsyncSession, wu: WebAppUser) -> User:
    return await users_svc.get_or_create(
        db, wu.telegram_id, username=wu.username, first_name=wu.first_name
    )


def _bal_dict(bal: UserBalance) -> dict:
    return {
        "total": bal.total_tokens,
        "used": bal.used_tokens,
        "remaining": bal.remaining,
        "expires_at": bal.expires_at.strftime("%Y-%m-%d") if bal.expires_at else None,
        "expired": bal.is_expired,
    }


# ---------------- bootstrap ----------------
@router.get("/bootstrap")
async def bootstrap(
    wu: WebAppUser = Depends(webapp_user), db: AsyncSession = Depends(get_session)
):
    user = await _db_user(db, wu)
    bal = await users_svc.get_balance(db, user.id)
    modes = (
        await db.execute(
            select(AIMode).where(AIMode.is_active.is_(True)).order_by(AIMode.sort_order)
        )
    ).scalars().all()
    # per-user engine allowlist (None = all)
    if user.allowed_modes is not None:
        modes = [m for m in modes if m.code in user.allowed_modes]
    packages = await pay_svc.list_active_packages(db)
    efforts = user.effort_overrides or {}
    return {
        "user": {
            "name": user.first_name or wu.first_name,
            "language": user.language,
            "is_admin": wu.is_admin,
            "unrestricted": user.unrestricted_usage,
            "default_mode": user.default_mode or "fast_chat",
        },
        "balance": _bal_dict(bal),
        "modes": [
            {
                "code": m.code,
                "fa_name": m.fa_name,
                "en_name": m.en_name,
                "description_fa": m.description_fa,
                "is_image": m.supports_image_output,
                "requires_confirmation": m.requires_confirmation,
                # effort is user-tunable on reasoning-capable text engines
                "can_effort": bool(
                    m.supports_text and not m.supports_image_output
                    and m.model.startswith(("gpt-5", "o3", "o4"))
                ),
                "effort": efforts.get(m.code) or (m.reasoning_effort or "none"),
                "default_effort": m.reasoning_effort or "none",
            }
            for m in modes
        ],
        "packages": [
            {
                "id": p.id, "name": p.name, "description": p.description,
                "price_usd": p.price_usd, "price_toman": p.price_toman,
                "ai_tokens": p.ai_tokens, "validity_days": p.validity_days,
            }
            for p in packages
        ],
    }


# ---------------- mode ----------------
class ModeBody(BaseModel):
    code: str


@router.post("/mode")
async def set_mode(
    body: ModeBody, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    mode = await chat_service.load_mode(db, body.code)
    if mode is None:
        raise HTTPException(404, "mode_not_found")
    user = await _db_user(db, wu)
    if not chat_service.mode_allowed(user, mode.code):
        raise HTTPException(403, "mode_not_allowed")
    user.default_mode = mode.code
    await db.commit()
    return {"ok": True, "default_mode": mode.code}


class EffortBody(BaseModel):
    code: str
    effort: str  # none|low|medium|high|xhigh


@router.post("/mode/effort")
async def set_effort(
    body: EffortBody, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    """User picks how hard the engine should think — cost scales with it."""
    effort = body.effort.strip().lower()
    if effort not in ("none", "low", "medium", "high", "xhigh"):
        raise HTTPException(422, "bad_effort")
    mode = await chat_service.load_mode(db, body.code)
    if mode is None:
        raise HTTPException(404, "mode_not_found")
    user = await _db_user(db, wu)
    if not chat_service.mode_allowed(user, mode.code):
        raise HTTPException(403, "mode_not_allowed")
    overrides = dict(user.effort_overrides or {})
    if effort == "none" or effort == (mode.reasoning_effort or "none"):
        overrides.pop(mode.code, None)  # back to the mode default
    else:
        overrides[mode.code] = effort
    user.effort_overrides = overrides
    await db.commit()
    return {"ok": True, "effort": effort}


# ---------------- chats ----------------
@router.get("/chats")
async def chats(
    wu: WebAppUser = Depends(webapp_user), db: AsyncSession = Depends(get_session)
):
    user = await _db_user(db, wu)
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.is_archived.is_(False))
            .order_by(Conversation.updated_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": c.id, "title": c.title or "…", "mode": c.current_mode,
            "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M"),
        }
        for c in rows
    ]


@router.get("/chats/{conv_id}/messages")
async def chat_messages(
    conv_id: str, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    user = await _db_user(db, wu)
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "not_found")
    msgs = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc()).limit(200)
        )
    ).scalars().all()
    return {
        "id": conv.id,
        "title": conv.title,
        "mode": conv.current_mode,
        "messages": [
            {
                "role": m.role, "content": m.content,
                "charged": m.charged_ai_tokens,
                "at": m.created_at.strftime("%H:%M"),
            }
            for m in msgs
        ],
    }


# ---------------- chat: file attach ----------------
ALLOWED_UPLOAD_EXT = {".pdf", ".txt", ".csv", ".md", ".json", ".log"}
MAX_UPLOAD_MB = 15


@router.post("/chat/upload")
async def chat_upload(
    request: Request,
    file: UploadFile = File(...),
    wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    from app.services.cost_estimator import count_tokens
    from app.services.file_extract import extract_text

    _rate_limit(wu.telegram_id, "upload", limit=10, window_s=600)
    user = await _db_user(db, wu)
    name = (file.filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(422, "file_type_not_allowed")

    buf = bytearray()
    limit = MAX_UPLOAD_MB * 1024 * 1024
    while chunk := await file.read(64 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, "file_too_large")
    raw = bytes(buf)

    fname = f"{new_uuid()}{ext}"
    path = STORAGE_DIR / fname
    path.write_bytes(raw)
    text = extract_text(path, file.filename or fname)
    if not text:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "extraction_failed")

    fa = FileAsset(
        user_id=user.id, original_filename=file.filename, mime_type=file.content_type,
        size_bytes=len(raw), storage_path=str(path), kind="document",
        status="stored", extracted_text=text,
    )
    db.add(fa)
    await db.commit()
    await db.refresh(fa)
    return {"file_id": fa.id, "name": file.filename, "tokens": count_tokens(text)}


async def _file_context(
    db: AsyncSession, user: User, file_id: str | None
) -> tuple[str | None, str | None]:
    if not file_id:
        return None, None
    fa = await db.get(FileAsset, file_id)
    if fa is None or fa.user_id != user.id or not fa.extracted_text:
        return None, None
    return fa.extracted_text, fa.original_filename


# ---------------- chat: estimate + send ----------------
class EstimateBody(BaseModel):
    text: str
    mode: str
    conv_id: str | None = None
    size: str = "1024x1024"
    quality: str = "medium"
    file_id: str | None = None


@router.post("/chat/estimate")
async def chat_estimate(
    body: EstimateBody, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    user = await _db_user(db, wu)
    mode = await chat_service.load_mode(db, body.mode)
    if mode is None:
        raise HTTPException(404, "mode_not_found")

    if mode.supports_image_output:
        econ = await get_economics(db)
        bal = await users_svc.get_balance(db, user.id)
        real_usd = pricing.IMAGE_FLAT_USD.get((body.size, body.quality), 0.05)
        markup = mode.markup_multiplier or econ.global_markup_multiplier
        charged = pricing.usd_to_ai_tokens(
            real_usd, markup=markup, unit_price_usd=econ.token_unit_price_usd,
            base_credit_cost=mode.base_credit_cost or 0,
            min_charge=econ.min_charge_per_request,
            max_charge=econ.max_charge_per_request,
        )
        return {
            "in_tokens": 0, "min": charged, "max": charged,
            "confirm": not user.unrestricted_usage, "balance": bal.remaining,
        }

    file_text, _ = await _file_context(db, user, body.file_id)
    est = await chat_service.estimate_turn(db, user, mode, body.text,
                                           file_text=file_text)
    return {
        "in_tokens": est.in_tokens,
        "min": est.min_credits,
        "max": est.max_credits,
        "confirm": est.requires_confirmation,
        "balance": est.balance,
    }


class SendBody(BaseModel):
    text: str
    mode: str
    conv_id: str | None = None
    cap: int | None = None
    size: str = "1024x1024"
    quality: str = "medium"
    file_id: str | None = None


@router.post("/chat/send")
async def chat_send(
    body: SendBody, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    user = await _db_user(db, wu)
    mode = await chat_service.load_mode(db, body.mode)
    if mode is None:
        raise HTTPException(404, "mode_not_found")
    if not chat_service.mode_allowed(user, mode.code):
        return {"ok": False, "error": "mode_not_allowed"}

    if mode.supports_image_output:
        return await _image_turn(db, user, mode, body)

    if not (body.text or "").strip():
        raise HTTPException(422, "empty_text")

    # SECURITY: never trust a client-supplied cap — derive the confirmed
    # upper bound server-side from our own estimate (body.cap is ignored).
    file_text, file_name = await _file_context(db, user, body.file_id)
    est = await chat_service.estimate_turn(db, user, mode, body.text.strip(),
                                           file_text=file_text)
    server_cap = None if user.unrestricted_usage else est.max_credits

    result = await chat_service.run_turn(
        db, user, mode, body.text.strip(), conv_id=body.conv_id, cap=server_cap,
        file_text=file_text, file_name=file_name,
    )
    if not result.ok:
        return {
            "ok": False, "error": result.error,
            "needed": result.needed, "balance": result.balance,
        }
    return {
        "ok": True, "conv_id": result.conv_id, "reply": result.reply,
        "charged": result.charged, "remaining": result.remaining,
    }


async def _image_turn(db: AsyncSession, user: User, mode: AIMode, body: SendBody):
    from app.services.openai_gateway import OpenAIError, generate_image

    size = body.size if body.size in ("1024x1024", "1024x1536", "1536x1024") else "1024x1024"
    quality = body.quality if body.quality in ("low", "medium", "high") else "medium"
    econ = await get_economics(db)
    bal = await users_svc.get_balance(db, user.id)

    real_usd = pricing.IMAGE_FLAT_USD.get((size, quality), 0.05)
    markup = mode.markup_multiplier or econ.global_markup_multiplier
    charged = pricing.usd_to_ai_tokens(
        real_usd, markup=markup, unit_price_usd=econ.token_unit_price_usd,
        base_credit_cost=mode.base_credit_cost or 0,
        min_charge=econ.min_charge_per_request, max_charge=econ.max_charge_per_request,
    )
    if bal.is_expired:
        return {"ok": False, "error": "expired", "balance": bal.remaining}
    if not user.unrestricted_usage and bal.remaining < charged:
        return {"ok": False, "error": "insufficient", "needed": charged,
                "balance": bal.remaining}

    try:
        img = await generate_image(db, mode.model, body.text, size=size, quality=quality)
    except OpenAIError as exc:
        log.warning("image error: %s", exc)
        await usage_svc.log_usage(
            db, user_id=user.id, conversation_id=None, message_id=None,
            model=mode.model, mode="image", input_tokens=0, output_tokens=0,
            reasoning_tokens=0, api_cost_usd=0.0, charged_ai_tokens=0,
            status="error", error_code=str(exc)[:60],
        )
        return {"ok": False, "error": "openai"}

    raw = base64.b64decode(img.b64)
    fname = f"{new_uuid()}.png"
    (STORAGE_DIR / fname).write_bytes(raw)
    db.add(FileAsset(
        user_id=user.id, original_filename=fname, mime_type="image/png",
        size_bytes=len(raw), storage_path=str(STORAGE_DIR / fname),
        kind="output", status="stored",
    ))
    await balance_svc.charge(db, user.id, charged)
    bal = await users_svc.get_balance(db, user.id)
    await usage_svc.log_usage(
        db, user_id=user.id, conversation_id=None, message_id=None,
        model=mode.model, mode="image", input_tokens=0, output_tokens=0,
        reasoning_tokens=0, api_cost_usd=real_usd, charged_ai_tokens=charged,
        status="ok",
    )
    return {
        "ok": True, "image_b64": img.b64, "charged": charged,
        "remaining": bal.remaining,
    }


# ---------------- usage ----------------
@router.get("/usage")
async def usage(
    wu: WebAppUser = Depends(webapp_user), db: AsyncSession = Depends(get_session)
):
    user = await _db_user(db, wu)
    bal = await users_svc.get_balance(db, user.id)
    per_mode = (
        await db.execute(
            select(
                UsageLog.mode,
                func.sum(UsageLog.charged_ai_tokens).label("charged"),
                func.count().label("n"),
            )
            .where(UsageLog.user_id == user.id, UsageLog.status == "ok")
            .group_by(UsageLog.mode)
            .order_by(func.sum(UsageLog.charged_ai_tokens).desc())
        )
    ).all()
    recent = (
        await db.execute(
            select(UsageLog).where(UsageLog.user_id == user.id)
            .order_by(UsageLog.created_at.desc()).limit(30)
        )
    ).scalars().all()
    return {
        "balance": _bal_dict(bal),
        "per_mode": [
            {"mode": r.mode, "charged": int(r.charged or 0), "count": r.n}
            for r in per_mode
        ],
        "recent": [
            {
                "at": l.created_at.strftime("%m-%d %H:%M"), "mode": l.mode,
                "in": l.input_tokens, "out": l.output_tokens,
                "charged": l.charged_ai_tokens, "status": l.status,
            }
            for l in recent
        ],
    }


# ---------------- recharge ----------------
@router.get("/payment-methods")
async def payment_methods(
    wu: WebAppUser = Depends(webapp_user), db: AsyncSession = Depends(get_session)
):
    methods = await pay_svc.list_active_methods(db)
    return [
        {
            "type": m.type, "display_name": m.display_name,
            "network": m.network, "value": decrypt(m.encrypted_value),
        }
        for m in methods
    ]


async def _notify_admins_receipt(
    request: Request, user: User, package: Package | None,
    receipt_id: str, photo_bytes: bytes | None,
) -> None:
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        return
    from aiogram.types import BufferedInputFile

    from app.bot.keyboards import receipt_review_kb

    amount = package.price_usd if package else "?"
    caption = t("fa", "new_receipt_admin",
                user=f"{user.first_name or ''} ({user.telegram_user_id})",
                package=(package.name if package else "—"), amount=amount)
    for admin_id in settings.admin_ids:
        try:
            if photo_bytes:
                await bot.send_photo(
                    admin_id,
                    BufferedInputFile(photo_bytes, filename="receipt.jpg"),
                    caption=caption, reply_markup=receipt_review_kb(receipt_id),
                )
            else:
                await bot.send_message(
                    admin_id, caption, reply_markup=receipt_review_kb(receipt_id)
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("notify admin failed: %s", exc)


@router.post("/receipt")
async def submit_receipt(
    request: Request,
    package_id: str = Form(...),
    txid: str = Form(""),
    photo: UploadFile | None = File(default=None),
    wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    _rate_limit(wu.telegram_id, "receipt", limit=5, window_s=600)
    # cheap first line of defense (Content-Length can lie; we also stream-check)
    try:
        declared = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        declared = 0
    if declared > (MAX_RECEIPT_MB + 2) * 1024 * 1024:
        raise HTTPException(413, "file_too_large")

    user = await _db_user(db, wu)
    package = await db.get(Package, package_id)
    if package is None or not package.is_active:
        raise HTTPException(404, "package_not_found")
    if not txid.strip() and photo is None:
        raise HTTPException(422, "txid_or_photo_required")

    photo_bytes: bytes | None = None
    file_asset_id: str | None = None
    if photo is not None:
        # read in chunks and abort as soon as the limit is crossed
        buf = bytearray()
        limit = MAX_RECEIPT_MB * 1024 * 1024
        while chunk := await photo.read(64 * 1024):
            buf.extend(chunk)
            if len(buf) > limit:
                raise HTTPException(413, "file_too_large")
        photo_bytes = bytes(buf)
        # trust magic bytes, not the client's content-type header
        real_mime = _sniff_image(photo_bytes)
        if real_mime is None:
            raise HTTPException(422, "image_required")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[real_mime]
        fname = f"receipt_{new_uuid()}{ext}"
        (STORAGE_DIR / fname).write_bytes(photo_bytes)
        fa = FileAsset(
            user_id=user.id, original_filename=photo.filename or fname,
            mime_type=real_mime, size_bytes=len(photo_bytes),
            storage_path=str(STORAGE_DIR / fname), kind="receipt", status="stored",
        )
        db.add(fa)
        await db.flush()
        file_asset_id = fa.id

    receipt = await pay_svc.create_receipt(
        db, user_id=user.id, package=package,
        txid=txid.strip() or None,
        method="miniapp",
    )
    if file_asset_id:
        receipt.receipt_file_id = file_asset_id
        await db.commit()

    # TxID present -> try automatic on-chain verification (auto-approve on match)
    if txid.strip():
        status, result = await pay_svc.process_txid_receipt(db, receipt, package)
        if status == "approved":
            bot = getattr(request.app.state, "bot", None)
            if bot:
                info = (f"✅ رسید خودکار تایید شد\n"
                        f"کاربر: {user.first_name or ''} ({user.telegram_user_id})\n"
                        f"پکیج: {package.name}\n"
                        f"{result.network} — {result.amount_usd:.2f}$" if result else "")
                for admin_id in settings.admin_ids:
                    try:
                        await bot.send_message(admin_id, info)
                    except Exception:  # noqa: BLE001
                        pass
            return {"ok": True, "receipt_id": receipt.id, "auto_approved": True,
                    "added": package.ai_tokens,
                    "network": result.network if result else ""}

    await _notify_admins_receipt(request, user, package, receipt.id, photo_bytes)
    return {"ok": True, "receipt_id": receipt.id, "auto_approved": False}


# ---------------- settings / support ----------------
class SettingsBody(BaseModel):
    language: str | None = None
    unrestricted: bool | None = None


@router.post("/settings")
async def save_settings(
    body: SettingsBody, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    user = await _db_user(db, wu)
    if body.language in ("fa", "en"):
        user.language = body.language
    if body.unrestricted is not None:
        # billing kill-switch — admin-only privilege
        if not wu.is_admin:
            raise HTTPException(403, "admin_only")
        user.unrestricted_usage = bool(body.unrestricted)
    await db.commit()
    return {"ok": True, "language": user.language,
            "unrestricted": user.unrestricted_usage}


class ExportBody(BaseModel):
    text: str
    filename: str = "پاسخ.md"


@router.post("/export")
async def export_to_telegram(
    body: ExportBody, request: Request, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    """Deliver content as a file into the user's own Telegram chat with the bot."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "empty_text")
    if len(text) > 400_000:
        raise HTTPException(413, "too_large")
    _rate_limit(wu.telegram_id, "export", limit=10, window_s=600)
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(503, "bot_offline")
    from aiogram.types import BufferedInputFile

    safe_name = (body.filename or "پاسخ.md")[:60]
    if not safe_name.endswith((".md", ".txt")):
        safe_name += ".md"
    try:
        await bot.send_document(
            wu.telegram_id,
            BufferedInputFile(text.encode("utf-8"), filename=safe_name),
            caption="📄 خروجی از مینی‌اپ",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("export failed: %s", exc)
        raise HTTPException(502, "send_failed")
    return {"ok": True}


class SupportBody(BaseModel):
    text: str


@router.post("/support")
async def support(
    body: SupportBody, request: Request, wu: WebAppUser = Depends(webapp_user),
    db: AsyncSession = Depends(get_session),
):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "empty_text")
    _rate_limit(wu.telegram_id, "support", limit=5, window_s=600)
    user = await _db_user(db, wu)
    bot = getattr(request.app.state, "bot", None)
    uname = f"@{user.username}" if user.username else ""
    fwd = f"🆘 پیام پشتیبانی (مینی‌اپ)\nاز: {user.telegram_user_id} {uname}\n\n{text[:3500]}"
    sent = False
    if bot is not None:
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, fwd)
                sent = True
            except Exception:  # noqa: BLE001
                pass
    return {"ok": sent}


# ---------------- admin ----------------
@router.get("/admin/overview")
async def admin_overview(
    wu: WebAppUser = Depends(webapp_admin), db: AsyncSession = Depends(get_session)
):
    kpis = await usage_svc.dashboard_kpis(db)
    econ = await get_economics(db)
    markup = econ.global_markup_multiplier or 1.0
    # real API $ that 10k credits represent (admin cost-awareness)
    cost_per_10k = round(10_000 * econ.token_unit_price_usd / markup, 2)
    pending = (
        await db.execute(
            select(PaymentReceipt).where(PaymentReceipt.status == "pending")
            .order_by(PaymentReceipt.created_at.desc()).limit(30)
        )
    ).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
    packages = {p.id: p for p in (await db.execute(select(Package))).scalars().all()}
    return {
        "kpis": {
            "today_cost": kpis["today_cost"], "month_cost": kpis["month_cost"],
            "revenue": kpis["revenue"], "profit": kpis["profit"],
            "active_users": kpis["active_users"], "total_users": kpis["total_users"],
            "pending_receipts": kpis["pending_receipts"],
            "failed_requests": kpis["failed_requests"],
        },
        "econ": {
            "unit_price_usd": econ.token_unit_price_usd,
            "markup": markup,
            "cost_per_10k_usd": cost_per_10k,
            "usd_to_toman_rate": int(
                await get_setting(db, "usd_to_toman_rate", "0") or 0
            ),
        },
        "pending": [
            {
                "id": r.id,
                "user": (users.get(r.user_id).first_name or "?") if users.get(r.user_id) else "?",
                "telegram_id": users.get(r.user_id).telegram_user_id if users.get(r.user_id) else None,
                "package": packages.get(r.package_id).name if r.package_id and packages.get(r.package_id) else "—",
                "amount": r.amount_usd, "txid": r.txid,
                "at": r.created_at.strftime("%m-%d %H:%M"),
            }
            for r in pending
        ],
    }


async def _notify_user(request: Request, db: AsyncSession, user_id: str, text: str):
    bot = getattr(request.app.state, "bot", None)
    target = await db.get(User, user_id)
    if bot is not None and target is not None:
        try:
            await bot.send_message(target.telegram_user_id, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("notify user failed: %s", exc)


@router.post("/admin/receipts/{receipt_id}/approve")
async def admin_approve(
    receipt_id: str, request: Request, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    admin_user = await _db_user(db, wu)
    try:
        receipt, added = await pay_svc.approve_receipt(db, receipt_id, admin_user.id)
    except ValueError:
        raise HTTPException(409, "not_pending")
    target = await db.get(User, receipt.user_id)
    await _notify_user(
        request, db, receipt.user_id,
        t(target.language if target else "fa", "receipt_approved_user", tokens=added),
    )
    return {"ok": True, "added": added}


class RejectBody(BaseModel):
    note: str = ""


@router.post("/admin/receipts/{receipt_id}/reject")
async def admin_reject(
    receipt_id: str, request: Request, body: RejectBody = RejectBody(),
    wu: WebAppUser = Depends(webapp_admin), db: AsyncSession = Depends(get_session),
):
    admin_user = await _db_user(db, wu)
    try:
        receipt = await pay_svc.reject_receipt(db, receipt_id, admin_user.id, body.note)
    except ValueError:
        raise HTTPException(404, "not_found")
    target = await db.get(User, receipt.user_id)
    suffix = f"\n{body.note}" if body.note else ""
    await _notify_user(
        request, db, receipt.user_id,
        t(target.language if target else "fa", "receipt_rejected_user", note=suffix),
    )
    return {"ok": True}


@router.get("/admin/users")
async def admin_users(
    wu: WebAppUser = Depends(webapp_admin), db: AsyncSession = Depends(get_session)
):
    rows = (
        await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    ).scalars().all()
    balances = {
        b.user_id: b for b in (await db.execute(select(UserBalance))).scalars().all()
    }
    out = []
    for u in rows:
        b = balances.get(u.id)
        out.append({
            "id": u.id, "name": u.first_name or "—", "username": u.username,
            "telegram_id": u.telegram_user_id, "role": u.role,
            "remaining": b.remaining if b else 0,
            "total": b.total_tokens if b else 0,
            "expires_at": b.expires_at.strftime("%Y-%m-%d") if b and b.expires_at else None,
            "allowed_modes": u.allowed_modes,  # None = all
        })
    return out


class AdjustBody(BaseModel):
    delta_total: int = 0
    expiry_days: int = -1


@router.post("/admin/users/{user_id}/adjust")
async def admin_adjust(
    user_id: str, body: AdjustBody, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user_not_found")
    bal = await balance_svc.adjust(
        db, user_id, delta_total=body.delta_total,
        set_expiry_days=(body.expiry_days if body.expiry_days >= 0 else None),
    )
    return {"ok": True, "remaining": bal.remaining, "total": bal.total_tokens}


class CreateUserBody(BaseModel):
    telegram_id: int
    first_name: str = ""
    credits: int = 0
    expiry_days: int = 30


@router.post("/admin/users/create")
async def admin_create_user(
    body: CreateUserBody, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    if body.telegram_id <= 0:
        raise HTTPException(422, "bad_telegram_id")
    existing = await users_svc.get_by_telegram_id(db, body.telegram_id)
    if existing is not None:
        raise HTTPException(409, "already_exists")
    user = await users_svc.get_or_create(
        db, body.telegram_id, first_name=(body.first_name or None)
    )
    if body.credits > 0:
        await balance_svc.adjust(
            db, user.id, delta_total=body.credits,
            set_expiry_days=max(1, body.expiry_days),
        )
    return {"ok": True, "id": user.id}


@router.post("/admin/users/{user_id}/delete")
async def admin_delete_user(
    user_id: str, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    from sqlalchemy import delete as sa_delete

    from app.models import Conversation, Message, UsageLog, UserBalance

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user_not_found")
    if settings.is_admin(target.telegram_user_id):
        raise HTTPException(403, "cannot_delete_admin")
    # purge dependents first (SQLite has no cascade here)
    await db.execute(sa_delete(Message).where(Message.user_id == user_id))
    await db.execute(sa_delete(Conversation).where(Conversation.user_id == user_id))
    await db.execute(sa_delete(UsageLog).where(UsageLog.user_id == user_id))
    await db.execute(sa_delete(FileAsset).where(FileAsset.user_id == user_id))
    await db.execute(sa_delete(PaymentReceipt).where(PaymentReceipt.user_id == user_id))
    await db.execute(sa_delete(UserBalance).where(UserBalance.user_id == user_id))
    await db.delete(target)
    await db.commit()
    return {"ok": True}


class UserModesBody(BaseModel):
    codes: list[str] | None = None  # None = all modes allowed


@router.post("/admin/users/{user_id}/modes")
async def admin_set_user_modes(
    user_id: str, body: UserModesBody, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user_not_found")
    if body.codes is None:
        target.allowed_modes = None
    else:
        valid = {
            m.code for m in (
                await db.execute(select(AIMode))
            ).scalars().all()
        }
        codes = [c for c in body.codes if c in valid]
        target.allowed_modes = codes
    await db.commit()
    return {"ok": True, "allowed_modes": target.allowed_modes}


@router.get("/admin/packages")
async def admin_packages(
    wu: WebAppUser = Depends(webapp_admin), db: AsyncSession = Depends(get_session)
):
    rows = (
        await db.execute(select(Package).order_by(Package.sort_order))
    ).scalars().all()
    return [
        {
            "id": p.id, "name": p.name, "price_usd": p.price_usd,
            "price_toman": p.price_toman, "ai_tokens": p.ai_tokens,
            "validity_days": p.validity_days, "is_active": p.is_active,
        }
        for p in rows
    ]


class PackagePriceBody(BaseModel):
    price_usd: float | None = None
    price_toman: int | None = None
    is_active: bool | None = None


@router.post("/admin/packages/{pkg_id}/update")
async def admin_update_package(
    pkg_id: str, body: PackagePriceBody, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    pkg = await db.get(Package, pkg_id)
    if pkg is None:
        raise HTTPException(404, "package_not_found")
    if body.price_usd is not None and body.price_usd >= 0:
        pkg.price_usd = body.price_usd
    if body.price_toman is not None:
        pkg.price_toman = body.price_toman if body.price_toman > 0 else None
    if body.is_active is not None:
        pkg.is_active = body.is_active
    await db.commit()
    return {"ok": True}


class ApplyRateBody(BaseModel):
    rate: int  # Toman per 1 USD


@router.post("/admin/packages/apply-rate")
async def admin_apply_rate(
    body: ApplyRateBody, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    """Set today's USD→Toman rate and refresh all package Toman prices."""
    if body.rate < 1_000 or body.rate > 100_000_000:
        raise HTTPException(422, "bad_rate")
    updated = await pay_svc.apply_toman_rate(db, body.rate)
    rows = (
        await db.execute(select(Package).order_by(Package.sort_order))
    ).scalars().all()
    return {
        "ok": True, "rate": body.rate, "updated": updated,
        "packages": [
            {"id": p.id, "name": p.name, "price_usd": p.price_usd,
             "price_toman": p.price_toman}
            for p in rows
        ],
    }


class BroadcastBody(BaseModel):
    text: str


@router.post("/admin/broadcast")
async def admin_broadcast(
    body: BroadcastBody, request: Request, wu: WebAppUser = Depends(webapp_admin),
    db: AsyncSession = Depends(get_session),
):
    """Send a message to every registered user via the bot."""
    import asyncio

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "empty_text")
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(503, "bot_offline")
    rows = (
        await db.execute(select(User).where(User.status == "active"))
    ).scalars().all()
    sent = failed = 0
    for u in rows:
        try:
            await bot.send_message(u.telegram_user_id, text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)  # stay well under telegram rate limits
    return {"ok": True, "sent": sent, "failed": failed}
