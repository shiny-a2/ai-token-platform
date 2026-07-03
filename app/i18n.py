"""Bilingual (fa/en) UI strings. Persian is the primary language.

Business logic must never hardcode copy — always go through t().
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # --- language / onboarding ---
    "choose_language": {
        "fa": "زبان خود را انتخاب کنید:",
        "en": "Please choose your language:",
    },
    "lang_set": {
        "fa": "زبان روی فارسی تنظیم شد. ✅",
        "en": "Language set to English. ✅",
    },
    "privacy_notice": {
        "fa": (
            "🔒 آگاهی حریم خصوصی\n\n"
            "پیام‌های شما برای ارائه سرویس، بازیابی چت، محاسبه مصرف، پشتیبانی و "
            "بکاپ روی سرور ذخیره می‌شوند. با ادامه، این موضوع را می‌پذیرید."
        ),
        "en": (
            "🔒 Privacy notice\n\n"
            "Your messages are stored on the server to deliver the service, recover "
            "chats, account usage, provide support and backups. By continuing you accept this."
        ),
    },
    "accept_continue": {"fa": "می‌پذیرم و ادامه", "en": "Accept & continue"},
    "welcome": {
        "fa": "به پلتفرم هوش مصنوعی خوش آمدید، {name} 👋\nاز منوی زیر شروع کنید.",
        "en": "Welcome to the AI platform, {name} 👋\nUse the menu below to start.",
    },
    # --- main menu ---
    "menu_new_chat": {"fa": "🤖 چت جدید", "en": "🤖 New chat"},
    "menu_my_chats": {"fa": "💬 چت‌های من", "en": "💬 My chats"},
    "menu_select_mode": {"fa": "🧠 انتخاب موتور", "en": "🧠 Select mode"},
    "menu_categories": {"fa": "📁 دسته‌بندی‌ها", "en": "📁 Categories"},
    "menu_files": {"fa": "📎 فایل‌ها", "en": "📎 Files"},
    "menu_image": {"fa": "🖼 تصویر", "en": "🖼 Image"},
    "menu_research": {"fa": "🔍 ریسرچ", "en": "🔍 Research"},
    "menu_recharge": {"fa": "💳 شارژ حساب", "en": "💳 Recharge"},
    "menu_usage": {"fa": "📊 مصرف من", "en": "📊 My usage"},
    "menu_settings": {"fa": "⚙️ تنظیمات", "en": "⚙️ Settings"},
    "menu_support": {"fa": "🆘 پشتیبانی", "en": "🆘 Support"},
    "main_menu_title": {"fa": "منوی اصلی:", "en": "Main menu:"},
    "back": {"fa": "⬅️ بازگشت", "en": "⬅️ Back"},
    "cancel": {"fa": "لغو", "en": "Cancel"},
    "send": {"fa": "ارسال", "en": "Send"},
    # --- modes ---
    "choose_mode_title": {
        "fa": "یک موتور را انتخاب کنید (هزینه‌ها تقریبی و به «اعتبار هوش مصنوعی» است):",
        "en": "Choose a mode (costs are approximate, in AI credits):",
    },
    "mode_selected": {
        "fa": "موتور فعال: {name}\nحالا پیام خود را بفرستید.",
        "en": "Active mode: {name}\nNow send your message.",
    },
    # --- chat ---
    "new_chat_started": {
        "fa": "چت جدید ساخته شد. موتور فعلی: {mode}\nپیام خود را بنویسید.",
        "en": "New chat created. Current mode: {mode}\nType your message.",
    },
    "no_active_chat": {
        "fa": "چت فعالی ندارید. «🤖 چت جدید» را بزنید.",
        "en": "No active chat. Tap “🤖 New chat”.",
    },
    "estimate_block": {
        "fa": (
            "موتور انتخابی: {mode}\n"
            "طول پرامپت شما: حدود {in_tok} توکن\n"
            "هزینه تقریبی این درخواست: {min}‌ تا {max} اعتبار\n"
            "موجودی شما: {balance} اعتبار\n\n"
            "آیا ارسال شود؟"
        ),
        "en": (
            "Selected mode: {mode}\n"
            "Your prompt length: ~{in_tok} tokens\n"
            "Estimated cost: {min}–{max} credits\n"
            "Your balance: {balance} credits\n\n"
            "Send it?"
        ),
    },
    "thinking": {"fa": "⏳ در حال پردازش…", "en": "⏳ Working…"},
    "charged_footer": {
        "fa": "\n\n— کسر شد: {charged} اعتبار | باقی‌مانده: {remaining}",
        "en": "\n\n— charged: {charged} credits | remaining: {remaining}",
    },
    # --- usage ---
    "usage_report": {
        "fa": (
            "📊 گزارش مصرف شما\n\n"
            "موجودی کل: {total} اعتبار\n"
            "مصرف‌شده: {used} اعتبار\n"
            "باقی‌مانده: {remaining} اعتبار\n"
            "اعتبار تا: {expires}\n"
        ),
        "en": (
            "📊 Your usage\n\n"
            "Total: {total} credits\n"
            "Used: {used} credits\n"
            "Remaining: {remaining} credits\n"
            "Valid until: {expires}\n"
        ),
    },
    "no_expiry": {"fa": "—", "en": "—"},
    # --- recharge / packages ---
    "choose_package": {
        "fa": "یک پکیج را انتخاب کنید:",
        "en": "Choose a package:",
    },
    "no_packages": {
        "fa": "فعلاً پکیجی تعریف نشده است. با پشتیبانی تماس بگیرید.",
        "en": "No packages defined yet. Contact support.",
    },
    "package_line": {
        "fa": "{name} — {price} — {tokens} اعتبار — {days} روز",
        "en": "{name} — {price} — {tokens} credits — {days} days",
    },
    "payment_instructions": {
        "fa": (
            "پکیج انتخابی: {name}\nمبلغ: {price}\n\n"
            "روش‌های پرداخت:\n{methods}\n\n"
            "پس از پرداخت، عکس رسید یا کد تراکنش (TxID) را همین‌جا ارسال کنید."
        ),
        "en": (
            "Selected: {name}\nAmount: {price}\n\n"
            "Payment methods:\n{methods}\n\n"
            "After paying, send the receipt photo or TxID here."
        ),
    },
    "no_payment_methods": {
        "fa": "روش پرداختی تنظیم نشده است. با ادمین تماس بگیرید.",
        "en": "No payment methods configured. Contact the admin.",
    },
    "receipt_received": {
        "fa": "✅ رسید شما دریافت شد و برای بررسی ادمین ارسال شد. پس از تایید، اعتبار اضافه می‌شود.",
        "en": "✅ Receipt received and sent to admin for review. Credit is added after approval.",
    },
    "receipt_approved_user": {
        "fa": "🎉 پرداخت شما تایید شد. {tokens} اعتبار به حساب شما اضافه شد.",
        "en": "🎉 Your payment was approved. {tokens} credits were added.",
    },
    "receipt_rejected_user": {
        "fa": "❌ متاسفانه رسید شما رد شد.{note}",
        "en": "❌ Your receipt was rejected.{note}",
    },
    # --- files / image / research ---
    "send_file_prompt": {
        "fa": "فایل خود را بفرستید (PDF، TXT یا تصویر). حجم مجاز محدود است.",
        "en": "Send your file (PDF, TXT or image). Size is limited.",
    },
    "file_stored": {
        "fa": "✅ فایل ذخیره شد ({size} کیلوبایت). می‌توانید دربارهٔ آن سوال بپرسید.",
        "en": "✅ File stored ({size} KB). You can now ask about it.",
    },
    "file_blocked": {
        "fa": "⛔️ این نوع فایل مجاز نیست.",
        "en": "⛔️ This file type is not allowed.",
    },
    "file_too_big": {
        "fa": "⛔️ حجم فایل بیش از حد مجاز است.",
        "en": "⛔️ File is larger than the allowed limit.",
    },
    "image_prompt": {
        "fa": "متن تصویری که می‌خواهید بسازید را بنویسید:",
        "en": "Describe the image you want to generate:",
    },
    "research_prompt": {
        "fa": "موضوع یا سوال ریسرچ را بنویسید. (هزینهٔ ریسرچ بالاتر است)",
        "en": "Write your research topic or question. (Research costs more)",
    },
    # --- settings ---
    "settings_title": {"fa": "⚙️ تنظیمات", "en": "⚙️ Settings"},
    "settings_language": {"fa": "🌐 تغییر زبان", "en": "🌐 Change language"},
    "settings_unrestricted_on": {"fa": "🔓 مصرف آزاد: روشن", "en": "🔓 Unrestricted: ON"},
    "settings_unrestricted_off": {"fa": "🔒 مصرف آزاد: خاموش", "en": "🔒 Unrestricted: OFF"},
    "support_text": {
        "fa": "برای پشتیبانی به ادمین پیام دهید. سوال خود را همین‌جا بنویسید تا برای ادمین ارسال شود.",
        "en": "For support, message the admin. Write your question here and it will be forwarded.",
    },
    # --- errors ---
    "err_insufficient": {
        "fa": (
            "اعتبار شما کافی نیست.\n"
            "موجودی فعلی: {balance} اعتبار\n"
            "هزینه تقریبی این درخواست: {needed} اعتبار\n"
            "برای ادامه حساب خود را شارژ کنید."
        ),
        "en": (
            "Insufficient balance.\n"
            "Current: {balance} credits\n"
            "Estimated cost: {needed} credits\n"
            "Please recharge to continue."
        ),
    },
    "err_expired": {
        "fa": "اعتبار شما منقضی شده است. لطفاً دوباره شارژ کنید.",
        "en": "Your credit has expired. Please recharge.",
    },
    "err_generic": {
        "fa": "خطایی رخ داد. لطفاً بعداً دوباره تلاش کنید.",
        "en": "Something went wrong. Please try again later.",
    },
    "err_openai": {
        "fa": "ارتباط با سرویس هوش مصنوعی برقرار نشد. اعتباری کسر نشد.",
        "en": "Could not reach the AI service. No credit was charged.",
    },
    "cancelled": {"fa": "لغو شد.", "en": "Cancelled."},
    # --- admin (telegram shortcut) ---
    "admin_panel": {
        "fa": "پنل ادمین:",
        "en": "Admin panel:",
    },
    "admin_open_dashboard": {"fa": "🖥 باز کردن داشبورد", "en": "🖥 Open dashboard"},
    "admin_pending_receipts": {"fa": "🧾 رسیدهای در انتظار", "en": "🧾 Pending receipts"},
    "admin_today_report": {"fa": "📈 گزارش امروز", "en": "📈 Today's report"},
    "admin_quick_credit": {"fa": "⚡️ افزودن اعتبار سریع", "en": "⚡️ Quick add credit"},
    "not_admin": {"fa": "شما دسترسی ادمین ندارید.", "en": "You are not an admin."},
    "new_receipt_admin": {
        "fa": "🧾 رسید جدید\nکاربر: {user}\nپکیج: {package}\nمبلغ: {amount}$\nبرای بررسی به داشبورد بروید.",
        "en": "🧾 New receipt\nUser: {user}\nPackage: {package}\nAmount: ${amount}\nReview it in the dashboard.",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    lang = lang if lang in ("fa", "en") else "fa"
    entry = STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get("fa") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
