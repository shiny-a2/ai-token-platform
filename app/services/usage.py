"""Usage-log writes + aggregate reporting for the admin dashboard."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Package, PaymentReceipt, UsageLog, User
from app.services.balance import utcnow


async def log_usage(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str | None,
    message_id: str | None,
    model: str,
    mode: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    api_cost_usd: float,
    charged_ai_tokens: int,
    status: str = "ok",
    error_code: str | None = None,
    tool_calls: dict | None = None,
) -> UsageLog:
    row = UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        model=model,
        mode=mode,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        api_cost_usd=api_cost_usd,
        charged_ai_tokens=charged_ai_tokens,
        status=status,
        error_code=error_code,
        tool_calls=tool_calls,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def dashboard_kpis(db: AsyncSession) -> dict:
    now = utcnow()
    day_start = now - timedelta(days=1)
    month_start = now - timedelta(days=30)

    async def cost_since(ts):
        return (
            await db.execute(
                select(func.coalesce(func.sum(UsageLog.api_cost_usd), 0.0)).where(
                    UsageLog.created_at >= ts
                )
            )
        ).scalar_one()

    today_cost = await cost_since(day_start)
    month_cost = await cost_since(month_start)

    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(PaymentReceipt.amount_usd), 0.0)).where(
                PaymentReceipt.status == "approved"
            )
        )
    ).scalar_one()

    active_users = (
        await db.execute(
            select(func.count(func.distinct(UsageLog.user_id))).where(
                UsageLog.created_at >= month_start
            )
        )
    ).scalar_one()

    total_users = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar_one()

    pending_receipts = (
        await db.execute(
            select(func.count()).select_from(PaymentReceipt).where(
                PaymentReceipt.status == "pending"
            )
        )
    ).scalar_one()

    failed_requests = (
        await db.execute(
            select(func.count()).select_from(UsageLog).where(UsageLog.status != "ok")
        )
    ).scalar_one()

    # top users by charged credits
    top_rows = (
        await db.execute(
            select(
                UsageLog.user_id,
                func.sum(UsageLog.charged_ai_tokens).label("credits"),
                func.sum(UsageLog.api_cost_usd).label("cost"),
            )
            .group_by(UsageLog.user_id)
            .order_by(func.sum(UsageLog.charged_ai_tokens).desc())
            .limit(10)
        )
    ).all()

    # top modes by real cost
    mode_rows = (
        await db.execute(
            select(
                UsageLog.mode,
                func.sum(UsageLog.api_cost_usd).label("cost"),
                func.count().label("n"),
            )
            .group_by(UsageLog.mode)
            .order_by(func.sum(UsageLog.api_cost_usd).desc())
            .limit(10)
        )
    ).all()

    return {
        "today_cost": round(today_cost, 4),
        "month_cost": round(month_cost, 4),
        "revenue": round(revenue, 2),
        "profit": round(revenue - month_cost, 2),
        "active_users": active_users,
        "total_users": total_users,
        "pending_receipts": pending_receipts,
        "failed_requests": failed_requests,
        "top_users": top_rows,
        "top_modes": mode_rows,
    }
