"""Aiogram routers, aggregated for registration."""
from __future__ import annotations

from aiogram import Router

from app.bot.handlers import admin, chat, media, menu, recharge, start


def build_root_router() -> Router:
    root = Router()
    # Order matters. Onboarding + commands first, then menu-button dispatch,
    # then stateful flows, and finally the catch-all free-text chat handler.
    root.include_router(start.router)
    root.include_router(admin.router)
    root.include_router(menu.router)
    root.include_router(recharge.router)
    root.include_router(media.router)
    root.include_router(chat.router)
    return root
