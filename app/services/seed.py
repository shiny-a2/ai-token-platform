"""Idempotent seeding of default AI modes, packages and economics settings."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt
from app.models import AIMode, Package, PaymentMethod, SystemSetting

DEFAULT_MODES = [
    dict(
        code="fast_chat", fa_name="⚡ سریع", en_name="⚡ Fast",
        description_fa="مناسب سوالات ساده و سریع.", description_en="Good for simple, quick questions.",
        model=settings.default_model, reasoning_effort=None,
        supports_text=True, base_credit_cost=1, max_output_tokens=800,
        requires_confirmation=False, sort_order=1,
    ),
    dict(
        code="smart_chat", fa_name="💡 هوشمند", en_name="💡 Smart",
        description_fa="مناسب کارهای عمومی و روزمره.", description_en="Good for general everyday tasks.",
        model=settings.default_model, reasoning_effort="low",
        supports_text=True, base_credit_cost=1, max_output_tokens=1500,
        requires_confirmation=False, sort_order=2,
    ),
    dict(
        code="thinking", fa_name="🧠 تینکینگ", en_name="🧠 Thinking",
        description_fa="مناسب تحلیل، کدنویسی و تصمیم‌گیری.", description_en="For analysis, coding and decisions.",
        model=settings.default_model, reasoning_effort="medium",
        supports_text=True, base_credit_cost=2, max_output_tokens=3000,
        requires_confirmation=True, sort_order=3,
    ),
    dict(
        code="deep_thinking", fa_name="🧠➕ تینکینگ عمیق", en_name="🧠➕ Deep thinking",
        description_fa="تحلیل عمیق؛ فقط با تایید مصرف.", description_en="Deep analysis; confirmation required.",
        model=settings.default_model, reasoning_effort="high",
        supports_text=True, base_credit_cost=3, max_output_tokens=4000,
        requires_confirmation=True, sort_order=4,
    ),
    dict(
        code="research", fa_name="🔍 ریسرچ", en_name="🔍 Research",
        description_fa="تحقیق با جستجو و منبع؛ هزینهٔ بالاتر.", description_en="Research with sources; higher cost.",
        model=settings.default_model, reasoning_effort="medium",
        supports_text=True, supports_web_search=True, supports_research=True,
        base_credit_cost=5, max_output_tokens=3000, requires_confirmation=True, sort_order=5,
    ),
    dict(
        code="image", fa_name="🖼 تصویر", en_name="🖼 Image",
        description_fa="تولید تصویر از متن.", description_en="Generate images from text.",
        model="gpt-image-1", reasoning_effort=None,
        supports_text=False, supports_image_output=True,
        base_credit_cost=0, max_output_tokens=1, requires_confirmation=True, sort_order=6,
    ),
    dict(
        code="vision", fa_name="👁 تحلیل عکس", en_name="👁 Vision",
        description_fa="تحلیل و توضیح تصویر ارسالی.", description_en="Analyse an uploaded image.",
        model=settings.default_model, reasoning_effort=None,
        supports_text=True, supports_image_input=True, supports_file_input=True,
        base_credit_cost=1, max_output_tokens=1500, requires_confirmation=False, sort_order=7,
    ),
]

DEFAULT_PACKAGES = [
    dict(name="Starter", price_usd=3, ai_tokens=5000, validity_days=30, sort_order=1,
         description="بستهٔ شروع"),
    dict(name="Standard", price_usd=5, ai_tokens=10000, validity_days=30, sort_order=2,
         description="بستهٔ استاندارد"),
    dict(name="Pro", price_usd=10, ai_tokens=25000, validity_days=30, sort_order=3,
         description="بستهٔ حرفه‌ای"),
    dict(name="Research Pack", price_usd=15, ai_tokens=35000, validity_days=30, sort_order=4,
         description="ویژهٔ ریسرچ", allowed_modes=None),
    dict(name="Image Pack", price_usd=10, ai_tokens=20000, validity_days=30, sort_order=5,
         description="ویژهٔ تصویر", allowed_modes=None),
]

ECON_DEFAULTS = {
    "token_unit_price_usd": str(settings.token_unit_price_usd),
    "global_markup_multiplier": str(settings.global_markup_multiplier),
    "min_charge_per_request": str(settings.min_charge_per_request),
    "max_charge_per_request": str(settings.max_charge_per_request),
    "support_contact": "@admin",
}


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def seed_all(db: AsyncSession) -> None:
    if await _count(db, AIMode) == 0:
        for m in DEFAULT_MODES:
            db.add(AIMode(**m))
    if await _count(db, Package) == 0:
        for p in DEFAULT_PACKAGES:
            db.add(Package(**p))
    if await _count(db, PaymentMethod) == 0:
        # disabled sample so the admin can edit real details in the panel
        db.add(
            PaymentMethod(
                type="card",
                display_name="نمونه کارت (غیرفعال — در پنل ویرایش کنید)",
                network=None,
                is_active=False,
                encrypted_value=encrypt("0000-0000-0000-0000"),
            )
        )
    for key, value in ECON_DEFAULTS.items():
        exists = await db.get(SystemSetting, key)
        if exists is None:
            db.add(SystemSetting(key=key, value=value, is_encrypted=False))
    await db.commit()
