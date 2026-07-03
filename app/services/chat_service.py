"""Shared chat-turn pipeline used by BOTH the Telegram bot and the Mini App API.

One code path for: balance gating -> context build -> OpenAI call ->
charge computation (with confirmed cap) -> persistence -> usage logging.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIMode, User
from app.services import balance as balance_svc
from app.services import conversation as conv_svc
from app.services import usage as usage_svc
from app.services import users as users_svc
from app.services.cost_estimator import (
    Estimate,
    compute_charge,
    count_tokens,
    estimate,
)
from app.services.openai_gateway import OpenAIError, chat as openai_chat
from app.services.settings_store import get_economics

log = logging.getLogger("chat_service")


async def load_mode(db: AsyncSession, code: str | None) -> AIMode | None:
    """Load an ACTIVE mode; disabled modes fall back to fast_chat."""
    if not code:
        code = "fast_chat"
    mode = (
        await db.execute(
            select(AIMode).where(AIMode.code == code, AIMode.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if mode is None and code != "fast_chat":
        mode = (
            await db.execute(
                select(AIMode).where(
                    AIMode.code == "fast_chat", AIMode.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
    return mode


@dataclass
class TurnEstimate:
    mode_code: str
    in_tokens: int
    min_credits: int
    max_credits: int
    requires_confirmation: bool
    balance: int


async def estimate_turn(
    db: AsyncSession, user: User, mode: AIMode, text: str,
    *, file_text: str | None = None,
) -> TurnEstimate:
    econ = await get_economics(db)
    context_tokens = count_tokens(file_text) if file_text else 0
    est: Estimate = estimate(mode, text, econ, context_tokens=context_tokens)
    bal = await users_svc.get_balance(db, user.id)
    return TurnEstimate(
        mode_code=mode.code,
        in_tokens=est.estimated_input_tokens,
        min_credits=est.estimated_ai_tokens_min,
        max_credits=est.estimated_ai_tokens_max,
        requires_confirmation=est.requires_confirmation and not user.unrestricted_usage,
        balance=bal.remaining,
    )


@dataclass
class TurnResult:
    ok: bool
    error: str | None = None          # expired | insufficient | openai | internal
    conv_id: str | None = None
    reply: str = ""
    charged: int = 0
    remaining: int = 0
    needed: int = 0
    balance: int = 0


async def run_turn(
    db: AsyncSession,
    user: User,
    mode: AIMode,
    text: str,
    *,
    conv_id: str | None = None,
    cap: int | None = None,
    skip_balance_gate: bool = False,
    file_text: str | None = None,
    file_name: str | None = None,
) -> TurnResult:
    """Execute one full chat turn. `cap` is the user-confirmed upper bound."""
    econ = await get_economics(db)
    bal = await users_svc.get_balance(db, user.id)

    if bal.is_expired:
        return TurnResult(ok=False, error="expired", balance=bal.remaining)

    if not skip_balance_gate and not user.unrestricted_usage:
        context_tokens = count_tokens(file_text) if file_text else 0
        est = estimate(mode, text, econ, context_tokens=context_tokens)
        if bal.remaining < est.estimated_ai_tokens_min:
            return TurnResult(
                ok=False, error="insufficient",
                needed=est.estimated_ai_tokens_min, balance=bal.remaining,
            )

    conv = await conv_svc.get_conversation(db, conv_id) if conv_id else None
    if conv is None or conv.user_id != user.id:
        conv = await conv_svc.create_conversation(
            db, user.id, mode_code=mode.code, title=text[:40]
        )
    elif conv.current_mode != mode.code:
        conv.current_mode = mode.code

    messages = await conv_svc.build_messages(
        db, conv, mode, text, file_text=file_text, file_name=file_name
    )

    try:
        result = await openai_chat(db, mode, messages)
    except OpenAIError as exc:
        log.warning("openai error: %s", exc)
        await usage_svc.log_usage(
            db, user_id=user.id, conversation_id=conv.id, message_id=None,
            model=mode.model, mode=mode.code, input_tokens=0, output_tokens=0,
            reasoning_tokens=0, api_cost_usd=0.0, charged_ai_tokens=0,
            status="error", error_code=str(exc)[:60],
        )
        return TurnResult(ok=False, error="openai", conv_id=conv.id,
                          balance=bal.remaining)

    effective_cap = None if user.unrestricted_usage else cap
    charge = compute_charge(
        mode, econ, result.input_tokens, result.output_tokens,
        result.reasoning_tokens, cap=effective_cap,
    )

    await conv_svc.add_message(
        db, conv, user.id, "user", text,
        input_tokens=result.input_tokens, mode=mode.code, model=mode.model,
    )
    asst = await conv_svc.add_message(
        db, conv, user.id, "assistant", result.text,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        reasoning_tokens=result.reasoning_tokens,
        charged=charge.charged_ai_tokens, api_cost_usd=charge.api_cost_usd,
        mode=mode.code, model=mode.model,
    )
    await balance_svc.charge(db, user.id, charge.charged_ai_tokens)
    bal = await users_svc.get_balance(db, user.id)
    await usage_svc.log_usage(
        db, user_id=user.id, conversation_id=conv.id, message_id=asst.id,
        model=mode.model, mode=mode.code, input_tokens=result.input_tokens,
        output_tokens=result.output_tokens, reasoning_tokens=result.reasoning_tokens,
        api_cost_usd=charge.api_cost_usd, charged_ai_tokens=charge.charged_ai_tokens,
        status="ok",
    )
    return TurnResult(
        ok=True, conv_id=conv.id, reply=result.text or "…",
        charged=charge.charged_ai_tokens, remaining=bal.remaining,
        balance=bal.remaining,
    )
