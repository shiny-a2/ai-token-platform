"""Bot + Dispatcher construction and command-menu setup."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from app.bot.handlers import build_root_router
from app.config import settings

log = logging.getLogger("bot.factory")


def create_bot() -> Bot:
    # parse_mode=None: we send plain text so arbitrary user/model output
    # never breaks Telegram entity parsing.
    return Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_root_router())
    return dp


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="شروع / انتخاب زبان — Start"),
            BotCommand(command="menu", description="منوی اصلی — Main menu"),
            BotCommand(command="admin", description="پنل ادمین — Admin"),
        ]
    )
    await setup_menu_button(bot)


async def setup_menu_button(bot: Bot) -> None:
    """Point the chat “☰” button at the Mini App when an HTTPS URL exists."""
    url = settings.public_url.rstrip("/")
    if not url.lower().startswith("https://"):
        log.info("PUBLIC_URL is not https — keeping the default commands menu")
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="منو", web_app=WebAppInfo(url=f"{url}/app")
            )
        )
        log.info("mini-app menu button set: %s/app", url)
    except Exception as exc:  # noqa: BLE001
        log.warning("set_chat_menu_button failed: %s", exc)
