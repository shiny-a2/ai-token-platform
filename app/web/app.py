"""FastAPI admin dashboard (server-rendered, dark cockpit theme)."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.crypto import decrypt, encrypt, mask
from app.db import get_session
from app.i18n import t
from app.models import (
    AIMode,
    Conversation,
    Message,
    Package,
    PaymentMethod,
    PaymentReceipt,
    ProviderApiKey,
    UsageLog,
    User,
    UserBalance,
)
from app.services import balance as balance_svc
from app.services import payments as pay_svc
from app.services import usage as usage_svc
from app.services.settings_store import all_settings, set_setting

log = logging.getLogger("web")
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class NotAuth(Exception):
    pass


def require_login(request: Request) -> bool:
    if not request.session.get("auth"):
        raise NotAuth()
    return True


def render(request: Request, name: str, active: str = "", **ctx) -> HTMLResponse:
    base = {"request": request, "active": active, "app_name": "AI Token Platform"}
    base.update(ctx)
    return templates.TemplateResponse(name, base)


def create_app(lifespan=None) -> FastAPI:
    app = FastAPI(title="AI Token Platform — Admin", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.app_secret)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Mini App API (authenticated per-request via Telegram initData)
    from app.web.webapp_api import router as webapp_router

    app.include_router(webapp_router)

    @app.exception_handler(NotAuth)
    async def _auth_redirect(request: Request, exc: NotAuth):
        return RedirectResponse("/admin/login", status_code=303)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/admin")

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    async def miniapp():
        # Served raw (not via Jinja) so JS braces are never mangled.
        html = (TEMPLATES_DIR / "webapp.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    # ---------------- auth ----------------
    @app.get("/admin/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return render(request, "login.html", error=None)

    @app.post("/admin/login")
    async def login(request: Request, password: str = Form(...)):
        if password == settings.admin_panel_password:
            request.session["auth"] = True
            return RedirectResponse("/admin", status_code=303)
        return render(request, "login.html", error="رمز عبور نادرست است.")

    @app.get("/admin/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/admin/login", status_code=303)

    # ---------------- dashboard ----------------
    @app.get("/admin", response_class=HTMLResponse)
    async def dashboard(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        kpis = await usage_svc.dashboard_kpis(db)
        # resolve top user display names
        top = []
        for row in kpis["top_users"]:
            u = await db.get(User, row.user_id)
            top.append({
                "name": (u.first_name if u else None) or (u.username if u else None) or (row.user_id[:8]),
                "credits": row.credits, "cost": round(row.cost or 0, 4),
            })
        return render(request, "dashboard.html", "dashboard", kpis=kpis, top=top)

    # ---------------- users ----------------
    @app.get("/admin/users", response_class=HTMLResponse)
    async def users_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
        balances = {
            b.user_id: b
            for b in (await db.execute(select(UserBalance))).scalars().all()
        }
        return render(request, "users.html", "users", users=rows, balances=balances)

    @app.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(
        user_id: str, request: Request, _=Depends(require_login),
        db: AsyncSession = Depends(get_session),
    ):
        user = await db.get(User, user_id)
        if not user:
            return RedirectResponse("/admin/users", status_code=303)
        bal = (await db.execute(
            select(UserBalance).where(UserBalance.user_id == user_id)
        )).scalar_one_or_none()
        logs = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user_id)
            .order_by(UsageLog.created_at.desc()).limit(50)
        )).scalars().all()
        convs = (await db.execute(
            select(Conversation).where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc()).limit(30)
        )).scalars().all()
        from app.services.settings_store import get_economics

        econ = await get_economics(db)
        cost_per_10k = round(
            10_000 * econ.token_unit_price_usd
            / (econ.global_markup_multiplier or 1.0), 2,
        )
        return render(request, "user_detail.html", "users",
                      user=user, bal=bal, logs=logs, convs=convs,
                      cost_per_10k=cost_per_10k)

    @app.post("/admin/users/{user_id}/adjust")
    async def adjust_balance(
        user_id: str, request: Request, _=Depends(require_login),
        delta_total: int = Form(0), expiry_days: int = Form(-1),
        db: AsyncSession = Depends(get_session),
    ):
        await balance_svc.adjust(
            db, user_id, delta_total=delta_total,
            set_expiry_days=(expiry_days if expiry_days >= 0 else None),
        )
        return RedirectResponse(f"/admin/users/{user_id}", status_code=303)

    # ---------------- receipts ----------------
    @app.get("/admin/receipts", response_class=HTMLResponse)
    async def receipts_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(
            select(PaymentReceipt).order_by(PaymentReceipt.created_at.desc()).limit(100)
        )).scalars().all()
        users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
        packages = {p.id: p for p in (await db.execute(select(Package))).scalars().all()}
        return render(request, "receipts.html", "receipts",
                      receipts=rows, users=users, packages=packages)

    @app.post("/admin/receipts/{receipt_id}/approve")
    async def approve(
        receipt_id: str, request: Request, _=Depends(require_login),
        db: AsyncSession = Depends(get_session),
    ):
        try:
            receipt, added = await pay_svc.approve_receipt(db, receipt_id, None)
            target = await db.get(User, receipt.user_id)
            bot = getattr(request.app.state, "bot", None)
            if bot and target:
                try:
                    await bot.send_message(
                        target.telegram_user_id,
                        t(target.language, "receipt_approved_user", tokens=added),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("notify failed: %s", exc)
        except ValueError:
            pass
        return RedirectResponse("/admin/receipts", status_code=303)

    @app.post("/admin/receipts/{receipt_id}/reject")
    async def reject(
        receipt_id: str, request: Request, _=Depends(require_login),
        note: str = Form(""), db: AsyncSession = Depends(get_session),
    ):
        try:
            receipt = await pay_svc.reject_receipt(db, receipt_id, None, note=note)
            target = await db.get(User, receipt.user_id)
            bot = getattr(request.app.state, "bot", None)
            if bot and target:
                suffix = f"\n{note}" if note else ""
                try:
                    await bot.send_message(
                        target.telegram_user_id,
                        t(target.language, "receipt_rejected_user", note=suffix),
                    )
                except Exception:  # noqa: BLE001
                    pass
        except ValueError:
            pass
        return RedirectResponse("/admin/receipts", status_code=303)

    # ---------------- packages ----------------
    @app.get("/admin/packages", response_class=HTMLResponse)
    async def packages_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        from app.services.settings_store import get_economics

        rows = (await db.execute(
            select(Package).order_by(Package.sort_order)
        )).scalars().all()
        econ = await get_economics(db)
        # Real API $ a package is worth if fully consumed:
        # charged_tokens = api_usd * markup / unit  =>  api_usd = tokens * unit / markup
        markup = econ.global_markup_multiplier or 1.0
        costs = {}
        for p in rows:
            cost = p.ai_tokens * econ.token_unit_price_usd / markup
            margin = p.price_usd - cost
            pct = (margin / p.price_usd * 100) if p.price_usd else 0
            costs[p.id] = {"cost": round(cost, 2), "margin": round(margin, 2),
                           "pct": round(pct)}
        from app.services.settings_store import get_setting

        toman_rate = await get_setting(db, "usd_to_toman_rate", "0")
        return render(request, "packages.html", "packages",
                      packages=rows, costs=costs, econ=econ,
                      toman_rate=int(toman_rate or 0))

    @app.post("/admin/packages/apply-rate")
    async def apply_rate(
        request: Request, _=Depends(require_login),
        rate: int = Form(...), db: AsyncSession = Depends(get_session),
    ):
        if 1_000 <= rate <= 100_000_000:
            await pay_svc.apply_toman_rate(db, rate)
        return RedirectResponse("/admin/packages", status_code=303)

    @app.post("/admin/packages/create")
    async def create_package(
        request: Request, _=Depends(require_login),
        name: str = Form(...), price_usd: float = Form(...), ai_tokens: int = Form(...),
        validity_days: int = Form(30), price_toman: int = Form(0),
        db: AsyncSession = Depends(get_session),
    ):
        db.add(Package(name=name, price_usd=price_usd, ai_tokens=ai_tokens,
                       validity_days=validity_days, is_active=True,
                       price_toman=(price_toman or None)))
        await db.commit()
        return RedirectResponse("/admin/packages", status_code=303)

    @app.post("/admin/packages/{pkg_id}/update")
    async def update_package(
        pkg_id: str, request: Request, _=Depends(require_login),
        name: str = Form(...), price_usd: float = Form(...), ai_tokens: int = Form(...),
        validity_days: int = Form(30), price_toman: int = Form(0),
        is_active: str = Form("off"), db: AsyncSession = Depends(get_session),
    ):
        pkg = await db.get(Package, pkg_id)
        if pkg:
            pkg.name, pkg.price_usd, pkg.ai_tokens = name, price_usd, ai_tokens
            pkg.validity_days = validity_days
            pkg.price_toman = price_toman or None
            pkg.is_active = is_active == "on"
            await db.commit()
        return RedirectResponse("/admin/packages", status_code=303)

    # ---------------- ai modes ----------------
    @app.get("/admin/modes", response_class=HTMLResponse)
    async def modes_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(select(AIMode).order_by(AIMode.sort_order))).scalars().all()
        return render(request, "modes.html", "modes", modes=rows)

    @app.post("/admin/modes/{mode_id}/update")
    async def update_mode(
        mode_id: str, request: Request, _=Depends(require_login),
        model: str = Form(...), reasoning_effort: str = Form(""),
        base_credit_cost: int = Form(0), markup_multiplier: float = Form(0),
        max_output_tokens: int = Form(2000), requires_confirmation: str = Form("off"),
        is_active: str = Form("off"), db: AsyncSession = Depends(get_session),
    ):
        m = await db.get(AIMode, mode_id)
        if m:
            m.model = model
            m.reasoning_effort = reasoning_effort or None
            m.base_credit_cost = base_credit_cost
            m.markup_multiplier = markup_multiplier or None
            m.max_output_tokens = max_output_tokens
            m.requires_confirmation = requires_confirmation == "on"
            m.is_active = is_active == "on"
            await db.commit()
        return RedirectResponse("/admin/modes", status_code=303)

    # ---------------- conversations ----------------
    @app.get("/admin/conversations", response_class=HTMLResponse)
    async def conversations_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)
        )).scalars().all()
        users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
        return render(request, "conversations.html", "conversations",
                      conversations=rows, users=users)

    @app.get("/admin/conversations/{conv_id}", response_class=HTMLResponse)
    async def conversation_detail(
        conv_id: str, request: Request, _=Depends(require_login),
        db: AsyncSession = Depends(get_session),
    ):
        conv = await db.get(Conversation, conv_id)
        if not conv:
            return RedirectResponse("/admin/conversations", status_code=303)
        msgs = (await db.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
        )).scalars().all()
        return render(request, "conversation_detail.html", "conversations",
                      conv=conv, msgs=msgs)

    # ---------------- usage ----------------
    @app.get("/admin/usage", response_class=HTMLResponse)
    async def usage_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(
            select(UsageLog).order_by(UsageLog.created_at.desc()).limit(200)
        )).scalars().all()
        users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
        return render(request, "usage.html", "usage", logs=rows, users=users)

    # ---------------- settings ----------------
    @app.get("/admin/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        vals = await all_settings(db)
        return render(request, "settings.html", "settings", vals=vals)

    @app.post("/admin/settings")
    async def save_settings(
        request: Request, _=Depends(require_login),
        token_unit_price_usd: str = Form(...), global_markup_multiplier: str = Form(...),
        min_charge_per_request: str = Form(...), max_charge_per_request: str = Form(...),
        support_contact: str = Form(""), db: AsyncSession = Depends(get_session),
    ):
        for key, value in {
            "token_unit_price_usd": token_unit_price_usd,
            "global_markup_multiplier": global_markup_multiplier,
            "min_charge_per_request": min_charge_per_request,
            "max_charge_per_request": max_charge_per_request,
            "support_contact": support_contact,
        }.items():
            await set_setting(db, key, value)
        return RedirectResponse("/admin/settings", status_code=303)

    # ---------------- payment methods ----------------
    @app.get("/admin/payment-methods", response_class=HTMLResponse)
    async def methods_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(select(PaymentMethod))).scalars().all()
        decoded = [
            {"m": m, "value": decrypt(m.encrypted_value)} for m in rows
        ]
        return render(request, "payment_methods.html", "methods", methods=decoded)

    @app.post("/admin/payment-methods/create")
    async def create_method(
        request: Request, _=Depends(require_login),
        type: str = Form(...), display_name: str = Form(...), value: str = Form(...),
        network: str = Form(""), db: AsyncSession = Depends(get_session),
    ):
        db.add(PaymentMethod(
            type=type, display_name=display_name, network=network or None,
            encrypted_value=encrypt(value), is_active=True,
        ))
        await db.commit()
        return RedirectResponse("/admin/payment-methods", status_code=303)

    @app.post("/admin/payment-methods/{method_id}/toggle")
    async def toggle_method(
        method_id: str, request: Request, _=Depends(require_login),
        db: AsyncSession = Depends(get_session),
    ):
        m = await db.get(PaymentMethod, method_id)
        if m:
            m.is_active = not m.is_active
            await db.commit()
        return RedirectResponse("/admin/payment-methods", status_code=303)

    # ---------------- api keys ----------------
    @app.get("/admin/api-keys", response_class=HTMLResponse)
    async def keys_page(
        request: Request, _=Depends(require_login), db: AsyncSession = Depends(get_session)
    ):
        rows = (await db.execute(
            select(ProviderApiKey).order_by(ProviderApiKey.priority)
        )).scalars().all()
        view = [{"k": k, "masked": mask(decrypt(k.encrypted_api_key))} for k in rows]
        return render(request, "api_keys.html", "keys", keys=view,
                      env_key_masked=mask(settings.openai_api_key))

    @app.post("/admin/api-keys/create")
    async def create_key(
        request: Request, _=Depends(require_login),
        name: str = Form(...), api_key: str = Form(...), priority: int = Form(100),
        db: AsyncSession = Depends(get_session),
    ):
        db.add(ProviderApiKey(
            name=name, encrypted_api_key=encrypt(api_key), priority=priority, is_active=True,
        ))
        await db.commit()
        return RedirectResponse("/admin/api-keys", status_code=303)

    @app.post("/admin/api-keys/{key_id}/toggle")
    async def toggle_key(
        key_id: str, request: Request, _=Depends(require_login),
        db: AsyncSession = Depends(get_session),
    ):
        k = await db.get(ProviderApiKey, key_id)
        if k:
            k.is_active = not k.is_active
            await db.commit()
        return RedirectResponse("/admin/api-keys", status_code=303)

    return app
