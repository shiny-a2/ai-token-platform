"""Single-process entrypoint: FastAPI dashboard + Telegram bot polling.

    python run.py            # run web + bot
    python run.py --seed     # just init db + seed defaults and exit
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn

from app.bot.factory import create_bot, create_dispatcher, setup_commands
from app.config import settings
from app.db import SessionLocal, init_db
from app.services.seed import seed_all
from app.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("run")


def _bot_token_ready() -> bool:
    tok = settings.bot_token
    return bool(tok) and ":" in tok and "FAKE" not in tok


@asynccontextmanager
async def lifespan(app):
    await init_db()
    async with SessionLocal() as db:
        await seed_all(db)
    log.info("database ready + defaults seeded")

    polling_task = None
    if _bot_token_ready():
        bot = create_bot()
        dp = create_dispatcher()
        app.state.bot = bot
        await setup_commands(bot)
        me = await bot.get_me()
        log.info("bot online: @%s", me.username)
        polling_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False)
        )
    else:
        app.state.bot = None
        log.warning(
            "BOT_TOKEN not set (or fake) — running dashboard ONLY. "
            "Fill .env then restart to enable the Telegram bot."
        )

    admins = ", ".join(str(x) for x in settings.admin_ids) or "— none —"
    log.info("dashboard: http://%s:%s/admin  | admins: %s",
             settings.web_host, settings.web_port, admins)
    try:
        yield
    finally:
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
            await app.state.bot.session.close()


app = create_app(lifespan=lifespan)


async def _seed_only() -> None:
    await init_db()
    async with SessionLocal() as db:
        await seed_all(db)
    log.info("seed complete")


def main() -> None:
    if "--seed" in sys.argv:
        asyncio.run(_seed_only())
        return
    uvicorn.run(
        app, host=settings.web_host, port=settings.web_port, log_level="info"
    )


if __name__ == "__main__":
    main()
