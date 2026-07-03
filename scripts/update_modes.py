"""Upgrade AI modes to the real gpt-5.x lineup + set global markup to 2.0.

Idempotent: safe to re-run. Run:  .venv\\Scripts\\python.exe scripts\\update_modes.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import AIMode
from app.services.settings_store import set_setting

# ChatGPT-app-like lineup: no artificial limits, user consciously picks and pays.
MODE_UPGRADES: dict[str, dict] = {
    "fast_chat": dict(model="gpt-5.4-nano", reasoning_effort=None,
                      max_output_tokens=16_000, requires_confirmation=False,
                      base_credit_cost=1),
    "smart_chat": dict(model="gpt-5.4-mini", reasoning_effort="low",
                       max_output_tokens=32_000, requires_confirmation=False,
                       base_credit_cost=1),
    "thinking": dict(model="gpt-5.5", reasoning_effort="medium",
                     max_output_tokens=64_000, requires_confirmation=True,
                     base_credit_cost=2),
    "deep_thinking": dict(model="gpt-5.5", reasoning_effort="high",
                          max_output_tokens=96_000, requires_confirmation=True,
                          base_credit_cost=3),
    # search-capable model; base covers the per-search fee (~$0.01 real ≈ 40 credits at 2x)
    "research": dict(model="gpt-5-search-api", reasoning_effort=None,
                     max_output_tokens=32_000, requires_confirmation=True,
                     base_credit_cost=40),
    "image": dict(model="gpt-image-2", reasoning_effort=None,
                  requires_confirmation=True, base_credit_cost=0),
    "vision": dict(model="gpt-5.4-mini", reasoning_effort="low",
                   max_output_tokens=32_000, requires_confirmation=False,
                   base_credit_cost=1),
}


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        for code, cfg in MODE_UPGRADES.items():
            mode = (
                await db.execute(select(AIMode).where(AIMode.code == code))
            ).scalar_one_or_none()
            if mode is None:
                print(f"skip (missing): {code}")
                continue
            for key, value in cfg.items():
                setattr(mode, key, value)
            print(f"updated {code}: {cfg.get('model')} "
                  f"effort={cfg.get('reasoning_effort')} "
                  f"max_out={cfg.get('max_output_tokens', '-')}")
        await db.commit()
        # user pays 2x the real usage (economic viability)
        await set_setting(db, "global_markup_multiplier", "2.0")
        print("global_markup_multiplier -> 2.0")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
