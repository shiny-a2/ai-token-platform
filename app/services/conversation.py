"""Conversation + message persistence and context assembly.

Three memory layers per the design doc: recent_messages, conversation_summary,
pinned_facts. build_messages() combines them into an OpenAI message list.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIMode, Conversation, Message

SYSTEM_BASE_FA = (
    "تو یک دستیار هوش مصنوعی فارسی‌زبان و مفید هستی. مختصر، دقیق و محترمانه پاسخ بده."
)


async def create_conversation(
    db: AsyncSession,
    user_id: str,
    *,
    mode_code: str,
    title: str | None = None,
) -> Conversation:
    conv = Conversation(
        user_id=user_id,
        current_mode=mode_code,
        title=title or "چت جدید",
        pinned_facts=[],
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(db: AsyncSession, conv_id: str) -> Conversation | None:
    return await db.get(Conversation, conv_id)


async def list_conversations(
    db: AsyncSession, user_id: str, *, limit: int = 20
) -> list[Conversation]:
    rows = (
        await db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.is_archived.is_(False),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def add_message(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    role: str,
    content: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    charged: int = 0,
    api_cost_usd: float = 0.0,
    mode: str | None = None,
    model: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conv.id,
        user_id=user_id,
        role=role,
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        charged_ai_tokens=charged,
        api_cost_usd=api_cost_usd,
        mode=mode,
        model=model,
    )
    db.add(msg)
    if role == "user" and (conv.title in (None, "", "چت جدید")):
        conv.title = content[:40]
    await db.commit()
    await db.refresh(msg)
    return msg


async def recent_messages(
    db: AsyncSession, conv_id: str, *, limit: int = 10
) -> list[Message]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


async def message_count(db: AsyncSession, conv_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conv_id
            )
        )
    ).scalar_one()


async def build_messages(
    db: AsyncSession,
    conv: Conversation,
    mode: AIMode,
    new_user_text: str,
    *,
    recent_limit: int = 10,
) -> list[dict]:
    system_parts = [SYSTEM_BASE_FA]
    if mode.description_fa:
        system_parts.append(mode.description_fa)
    if conv.summary:
        system_parts.append("خلاصهٔ گفتگوی قبلی:\n" + conv.summary)
    if conv.pinned_facts:
        facts = "\n".join(f"- {f}" for f in conv.pinned_facts if f)
        if facts:
            system_parts.append("نکات مهم ذخیره‌شده:\n" + facts)

    messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    for m in await recent_messages(db, conv.id, limit=recent_limit):
        if m.role in ("user", "assistant") and m.content:
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": new_user_text})
    return messages
