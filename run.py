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


async def _menu_url_sync(bot) -> None:
    """Keep the mini-app menu button pointed at the FASTEST healthy URL.

    Preference: the Cloudflare quick tunnel (edge network — much faster for
    users on throttled international routes) when its service is up; falls
    back to the stable PUBLIC_URL otherwise. The tunnel URL changes on every
    tunnel restart, so we re-read it from the tunnel service log and verify
    it end-to-end before switching.
    """
    import re
    from pathlib import Path

    import httpx
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    tunnel_log = Path("data/svclogs/AITokenPlatform-Tunnel.err.log")
    current: str | None = None

    async def probe(base: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8, verify=True) as client:
                r = await client.get(f"{base}/health")
                return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def set_menu(base: str) -> None:
        nonlocal current
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="منو", web_app=WebAppInfo(url=f"{base}/app"))
        )
        current = base
        log.info("menu button -> %s/app", base)

    while True:
        try:
            candidate = None
            if tunnel_log.exists():
                tail = tunnel_log.read_text(encoding="utf-8", errors="ignore")[-30000:]
                urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", tail)
                if urls:
                    candidate = urls[-1]
            if candidate and candidate != current and await probe(candidate):
                await set_menu(candidate)
            elif candidate is None or (candidate == current and not await probe(candidate)):
                # tunnel gone/dead -> fall back to the stable address
                stable = settings.public_url.rstrip("/")
                if stable.startswith("https://") and current != stable and await probe(stable):
                    await set_menu(stable)
        except Exception as exc:  # noqa: BLE001
            log.debug("menu sync: %s", exc)
        await asyncio.sleep(60)


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
        app.state.menu_sync_task = asyncio.create_task(_menu_url_sync(bot))
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
        sync_task = getattr(app.state, "menu_sync_task", None)
        if sync_task:
            sync_task.cancel()
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
