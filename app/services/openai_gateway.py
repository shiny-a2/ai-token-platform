"""Thin gateway over the OpenAI API with key failover + usage extraction.

Never exposes API keys to the caller. Keys come from the DB (encrypted,
priority-ordered) and fall back to OPENAI_API_KEY from the environment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt
from app.models import AIMode, ProviderApiKey
from app.services.balance import utcnow

log = logging.getLogger("openai_gateway")


class OpenAIError(Exception):
    pass


@dataclass
class ChatResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    model: str = ""


@dataclass
class ImageResult:
    b64: str
    model: str = ""
    size: str = ""
    quality: str = ""


@dataclass
class _KeyRef:
    row_id: str | None
    name: str
    key: str
    tried: bool = field(default=False)


async def _candidate_keys(db: AsyncSession) -> list[_KeyRef]:
    refs: list[_KeyRef] = []
    rows = (
        await db.execute(
            select(ProviderApiKey)
            .where(ProviderApiKey.is_active.is_(True))
            .order_by(ProviderApiKey.priority.asc())
        )
    ).scalars().all()
    for r in rows:
        key = decrypt(r.encrypted_api_key)
        if key:
            refs.append(_KeyRef(row_id=r.id, name=r.name, key=key))
    if settings.openai_api_key:
        if not any(x.key == settings.openai_api_key for x in refs):
            refs.append(_KeyRef(row_id=None, name="env", key=settings.openai_api_key))
    return refs


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 529):
        return True
    text = str(exc).lower()
    return "rate limit" in text or "quota" in text or "overloaded" in text


async def _mark_used(db: AsyncSession, ref: _KeyRef, status: str) -> None:
    if ref.row_id is None:
        return
    row = await db.get(ProviderApiKey, ref.row_id)
    if row:
        row.last_used_at = utcnow()
        row.status = status
        await db.commit()


async def chat(
    db: AsyncSession,
    mode: AIMode,
    messages: list[dict],
    *,
    effort_override: str | None = None,
) -> ChatResult:
    keys = await _candidate_keys(db)
    if not keys:
        raise OpenAIError("no_api_key")

    last_exc: Exception | None = None
    for ref in keys:
        client = AsyncOpenAI(api_key=ref.key)
        try:
            kwargs: dict = {
                "model": mode.model,
                "messages": messages,
                "max_completion_tokens": mode.max_output_tokens,
            }
            effort = (effort_override or mode.reasoning_effort or "").strip().lower()
            if effort and effort != "none" and mode.model.startswith(("gpt-5", "o3", "o4")):
                # gpt-5.x accepts xhigh natively; older o-series caps at high
                if not mode.model.startswith("gpt-5"):
                    effort = {"xhigh": "high"}.get(effort, effort)
                kwargs["reasoning_effort"] = effort
            resp = await client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            usage = resp.usage
            reasoning = 0
            if usage and getattr(usage, "completion_tokens_details", None):
                reasoning = getattr(
                    usage.completion_tokens_details, "reasoning_tokens", 0
                ) or 0
            await _mark_used(db, ref, "ok")
            return ChatResult(
                text=choice.message.content or "",
                input_tokens=(usage.prompt_tokens if usage else 0),
                output_tokens=(usage.completion_tokens if usage else 0),
                reasoning_tokens=reasoning,
                model=mode.model,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("chat via key %s failed: %s", ref.name, exc)
            await _mark_used(db, ref, "error")
            if _is_retryable(exc):
                continue
            raise OpenAIError(str(exc)) from exc
    raise OpenAIError(str(last_exc) if last_exc else "all_keys_failed")


async def generate_image(
    db: AsyncSession,
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    quality: str = "medium",
) -> ImageResult:
    keys = await _candidate_keys(db)
    if not keys:
        raise OpenAIError("no_api_key")
    last_exc: Exception | None = None
    for ref in keys:
        client = AsyncOpenAI(api_key=ref.key)
        try:
            resp = await client.images.generate(
                model=model, prompt=prompt, size=size, quality=quality, n=1
            )
            b64 = resp.data[0].b64_json or ""
            await _mark_used(db, ref, "ok")
            return ImageResult(b64=b64, model=model, size=size, quality=quality)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("image via key %s failed: %s", ref.name, exc)
            await _mark_used(db, ref, "error")
            if _is_retryable(exc):
                continue
            raise OpenAIError(str(exc)) from exc
    raise OpenAIError(str(last_exc) if last_exc else "all_keys_failed")
