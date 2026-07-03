"""Reply + inline keyboards and the language-agnostic menu matcher."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t
from app.models import AIMode, Package

# action -> i18n key
MENU_ACTIONS = {
    "new_chat": "menu_new_chat",
    "my_chats": "menu_my_chats",
    "select_mode": "menu_select_mode",
    "categories": "menu_categories",
    "files": "menu_files",
    "image": "menu_image",
    "research": "menu_research",
    "recharge": "menu_recharge",
    "usage": "menu_usage",
    "settings": "menu_settings",
    "support": "menu_support",
}


def match_menu(text: str) -> str | None:
    """Map an incoming button label (fa or en) back to an action id."""
    if not text:
        return None
    text = text.strip()
    for action, key in MENU_ACTIONS.items():
        if text in (t("fa", key), t("en", key)):
            return action
    return None


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    def b(key: str) -> KeyboardButton:
        return KeyboardButton(text=t(lang, key))

    rows = [
        [b("menu_new_chat"), b("menu_my_chats")],
        [b("menu_select_mode"), b("menu_usage")],
        [b("menu_image"), b("menu_research")],
        [b("menu_files"), b("menu_recharge")],
        [b("menu_settings"), b("menu_support")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="lang:fa"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


def modes_kb(modes: list[AIMode], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for m in modes:
        name = m.fa_name if lang == "fa" else m.en_name
        rows.append([InlineKeyboardButton(text=name, callback_data=f"mode:{m.code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price_label(p: Package, lang: str) -> str:
    """Toman first (Persian audience) when set, else USD."""
    if p.price_toman:
        return f"{p.price_toman:,} تومان" if lang == "fa" else f"{p.price_toman:,} Toman"
    return f"{_num(p.price_usd)}$"


def packages_kb(packages: list[Package], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for p in packages:
        label = t(lang, "package_line", name=p.name, price=price_label(p, lang),
                  tokens=p.ai_tokens, days=p.validity_days)
        rows.append([InlineKeyboardButton(text=label, callback_data=f"pkg:{p.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "send"), callback_data="send:yes"),
                InlineKeyboardButton(text=t(lang, "cancel"), callback_data="send:no"),
            ]
        ]
    )


def image_size_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬛️ 1:1", callback_data="imgsize:1024x1024"),
                InlineKeyboardButton(text="📱 9:16", callback_data="imgsize:1024x1536"),
                InlineKeyboardButton(text="🖥 16:9", callback_data="imgsize:1536x1024"),
            ]
        ]
    )


def admin_kb(lang: str, dashboard_url: str) -> InlineKeyboardMarkup:
    from aiogram.types import WebAppInfo

    rows: list[list[InlineKeyboardButton]] = []
    if dashboard_url.lower().startswith("https://"):
        # web_app buttons require HTTPS; open the mini app's admin tab
        base = dashboard_url.rsplit("/admin", 1)[0]
        rows.append([InlineKeyboardButton(
            text="🛡 مینی‌اپ ادمین", web_app=WebAppInfo(url=f"{base}/app"))])
        rows.append([InlineKeyboardButton(
            text=t(lang, "admin_open_dashboard"), url=dashboard_url)])
    rows.append([InlineKeyboardButton(
        text=t(lang, "admin_pending_receipts"), callback_data="admin:receipts")])
    rows.append([InlineKeyboardButton(
        text=t(lang, "admin_today_report"), callback_data="admin:today")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_review_kb(receipt_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تایید", callback_data=f"rcpt:ok:{receipt_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"rcpt:no:{receipt_id}"),
            ]
        ]
    )


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}"
