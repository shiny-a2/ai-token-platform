# AI Token Platform

ربات تلگرامی هوش مصنوعی با حسابداری اعتبار داخلی، فروش پکیج، پرداخت دستی
(کارت‌به‌کارت / کریپتو) و داشبورد مدیریتی تحت وب.

> نسخهٔ اول: SQLite + داشبورد سمت‌سرور (FastAPI + Jinja) + مدل پیش‌فرض `gpt-4o-mini`
> که همه‌چیز از پنل ادمین قابل تنظیم است.

## معماری

```
Telegram (aiogram) ──┐
                     ├─► FastAPI process ─► services ─► OpenAI Gateway ─► OpenAI
Admin Web (Jinja) ───┘        │
                              └─► SQLite (SQLAlchemy async)
```

- `app/models.py` — کل اسکیمای دیتابیس (users, packages, balances, receipts, ai_modes,
  conversations, messages, usage_logs, files, api_keys, settings, audit logs).
- `app/services/` — لایهٔ منطق: تخمین هزینه، دروازهٔ OpenAI با failover کلید، حسابداری
  اعتبار، پرداخت، گفتگو، seed.
- `app/bot/` — ربات: انتخاب زبان، منو، انتخاب موتور، تخمین/تایید هزینه، تصویر، ریسرچ،
  ویژن، فایل، شارژ حساب، پشتیبانی، میان‌بر `/admin`.
- `app/web/` — داشبورد ادمین: KPIها، کاربران، رسیدها، پکیج‌ها، موتورها، گفتگوها، مصرف،
  روش‌های پرداخت، کلیدهای API، تنظیمات اقتصادی.

## راه‌اندازی

```bash
python -m venv .venv
.venv\Scripts\activate           # ویندوز
pip install -r requirements.txt

copy .env.example .env           # سپس مقادیر واقعی را پر کنید
python run.py
```

مقادیر لازم در `.env`:

- `BOT_TOKEN` — توکن ربات از BotFather
- `ADMIN_TELEGRAM_ID` — آیدی عددی مالک (از @userinfobot)
- `OPENAI_API_KEY` — کلید OpenAI
- `ADMIN_PANEL_PASSWORD` — رمز ورود به داشبورد
- `APP_SECRET` — رشتهٔ تصادفی برای امضای کوکی و رمزنگاری تنظیمات حساس

سپس:

- ربات: در تلگرام `/start`
- داشبورد: `http://<server>:8095/admin`

اگر `BOT_TOKEN` تنظیم نشده باشد، فقط داشبورد بالا می‌آید تا بتوانید پیکربندی کنید.

## امنیت

- کلید OpenAI و اطلاعات پرداخت به‌صورت رمزنگاری‌شده (Fernet مشتق از `APP_SECRET`) ذخیره می‌شوند.
- `.env`، `storage/`، `data/`، `backups/` در `.gitignore` هستند.
- دسترسی ادمین در تلگرام فقط برای `ADMIN_TELEGRAM_ID` مجاز است.

## تصمیم‌های نسخهٔ اول

- «token» در UI فارسی «اعتبار هوش مصنوعی» نمایش داده می‌شود تا با توکن OpenAI اشتباه نشود.
- برای موتورهای گران و تصویر/ریسرچ، پیش از اجرا تخمین هزینه و تایید گرفته می‌شود.
- سقف کسر هر درخواست از بازهٔ تاییدشده بالاتر نمی‌رود، مگر «مصرف آزاد» فعال باشد.
