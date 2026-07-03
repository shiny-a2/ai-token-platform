# AI Token Platform

A Telegram-based AI assistant platform with its own credit economy. Users chat with
OpenAI models through a Telegram bot or a full Telegram Mini App, pay for exactly what
they use in internal "AI credits", and top up through manually-reviewed payments
(bank transfer or crypto). A single admin runs everything from a web dashboard and
an admin tab inside the Mini App.

I built this to give my team and friends metered access to frontier models without
everyone needing their own subscription — and to keep the economics honest: every
request is estimated up front, confirmed by the user when it's expensive, and charged
from real API usage with a configurable markup.

## What it does

**For users (Persian-first UI, English available):**

- Chat with selectable engines — fast / smart / thinking / deep thinking / research
  (with live web search) / image generation / vision — each mapped to a different
  OpenAI model and reasoning effort
- See an estimated credit cost *before* sending anything expensive, and confirm it;
  the confirmed upper bound is enforced server-side, so the bill can't surprise them
- Full chat inside a Telegram Mini App (conversation list, history, engine picker,
  usage breakdown), opened from the bot's menu button
- Top up by choosing a package, paying card-to-card or crypto, and submitting a
  receipt photo or TxID — activation happens after admin approval
- Track balance, per-engine usage, and expiry at any time

**For the admin:**

- Web dashboard: KPIs (real API cost vs. revenue vs. estimated profit), users,
  balance adjustments, receipt review, package CRUD with cost/margin per package,
  engine configuration (model, reasoning effort, markup, output caps), conversation
  audit, usage logs, encrypted payment methods, encrypted spare API keys
- The same essentials inside the Mini App's admin tab: approve/reject receipts with
  one tap, adjust user balances, see pending work — receipts also land in the
  admin's Telegram DM with inline approve/reject buttons
- Everything money-related is tunable at runtime: credit unit price, global markup,
  per-engine markup, min/max charge per request

## Architecture

```
Telegram user
   ├── aiogram bot (polling) ──┐
   └── Mini App (vanilla JS) ──┤   one process
                               ▼
                        FastAPI backend
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
        service layer   admin web    Mini App API
        (chat, cost,    (Jinja,      (initData HMAC
         balance,        session      auth per
         payments)       auth)        request)
              │
              ▼
     OpenAI gateway (encrypted keys, priority failover)
              │
              ▼
     SQLite (async SQLAlchemy 2.0) — swappable for Postgres
```

Design decisions worth calling out:

- **One code path for money.** The bot and the Mini App share the same
  `chat_service.run_turn()` pipeline: balance gate → context build → OpenAI call →
  charge computation (capped at the user-confirmed bound) → persistence → usage log.
  There is no way to chat that skips accounting.
- **The server never trusts the client about cost.** Estimates and charge caps are
  recomputed server-side; the Mini App's numbers are display-only.
- **Mini App auth is per-request.** Every API call carries Telegram's signed
  `initData`, validated with the HMAC scheme from Telegram's spec (constant-time
  compare, freshness window). No sessions, no tokens to leak.
- **Secrets live in one place.** Payment details and spare OpenAI keys are stored
  Fernet-encrypted in the database (key derived from `APP_SECRET`); the `.env` file
  is the only plaintext secret store and never leaves the machine.
- **Credit math is auditable.** `charged = base + ceil(real_api_usd × markup / unit_price)`,
  logged per request with input/output/reasoning token counts and the real USD cost,
  so revenue vs. cost is always reconcilable.

## Stack

Python 3.12 · FastAPI · aiogram 3 · SQLAlchemy 2 (async, SQLite) · Jinja2 ·
OpenAI SDK · tiktoken · cryptography (Fernet) · vanilla JS Mini App (no build step)

## Getting started

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows
pip install -r requirements.txt

cp .env.example .env              # fill in BOT_TOKEN, ADMIN_TELEGRAM_ID,
                                  # OPENAI_API_KEY, ADMIN_PANEL_PASSWORD, APP_SECRET
python run.py
```

- Bot: send `/start` to your bot
- Dashboard: `http://localhost:8095/admin`
- Mini App: needs a public HTTPS URL in `PUBLIC_URL`; the bot sets its menu button
  automatically on startup. For development, `scripts/start_all.ps1` boots a
  Cloudflare quick tunnel, writes the URL into `.env`, and starts the server.

Without a bot token the server runs dashboard-only, which is handy for configuring
packages and payment methods first.

## Testing

```bash
python scripts/webapp_test.py   # 15 end-to-end tests: signed initData auth,
                                # admin gating, a real chat turn, charge caps,
                                # conversation isolation, receipt flow
python scripts/smoke_test.py    # renders every dashboard page
```

The Mini App test suite signs real `initData` payloads (with a throwaway token) so
the HMAC validation path is exercised for real, and asserts the security
properties that matter: non-admins can't reach admin endpoints, users can't read
each other's conversations, client-supplied charge caps are ignored.

## Operations

- `scripts/start_all.ps1` — boot orchestrator (tunnel → URL → server), registered
  as a Windows Scheduled Task so everything survives reboots
- `scripts/backup.py` — daily zip of the database (via SQLite's online backup API)
  and file storage, 30-day retention, scheduled at 03:30

## Security model

- Admin access is bound to a Telegram user id allowlist; the web dashboard adds a
  password on top with signed session cookies
- The billing kill-switch (`unrestricted_usage`) is an admin-granted privilege —
  users cannot toggle it themselves
- Receipt uploads are size-limited while streaming, validated by magic bytes (not
  the client's content-type), and rate-limited per user
- All admin actions on user conversations are designed to be audit-logged
- Nothing sensitive is committed: real `.env`, database, storage, and backups are
  git-ignored; this repository contains fake sample values only

## Roadmap

- File Q&A inside the Mini App (PDF/text upload → ask about it)
- Conversation summarization to cut context cost on long chats
- Automatic crypto payment verification (TxID lookup)
- Postgres + Docker Compose deployment profile
- Per-package engine allowlists

## License

MIT
