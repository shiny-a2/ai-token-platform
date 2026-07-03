"""Manual payment flow: receipts, approval, activation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.models import Package, PaymentMethod, PaymentReceipt
from app.services import balance
from app.services.balance import utcnow


async def list_active_packages(db: AsyncSession) -> list[Package]:
    rows = (
        await db.execute(
            select(Package)
            .where(Package.is_active.is_(True))
            .order_by(Package.sort_order.asc(), Package.price_usd.asc())
        )
    ).scalars().all()
    return list(rows)


async def list_active_methods(db: AsyncSession) -> list[PaymentMethod]:
    rows = (
        await db.execute(
            select(PaymentMethod).where(PaymentMethod.is_active.is_(True))
        )
    ).scalars().all()
    return list(rows)


def format_methods(methods: list[PaymentMethod]) -> str:
    lines = []
    for m in methods:
        value = decrypt(m.encrypted_value)
        net = f" ({m.network})" if m.network else ""
        lines.append(f"• {m.display_name}{net}:\n  {value}")
    return "\n".join(lines)


async def create_receipt(
    db: AsyncSession,
    *,
    user_id: str,
    package: Package | None,
    telegram_file_id: str | None = None,
    txid: str | None = None,
    method: str | None = None,
) -> PaymentReceipt:
    receipt = PaymentReceipt(
        user_id=user_id,
        package_id=package.id if package else None,
        method=method,
        amount_usd=package.price_usd if package else None,
        telegram_file_id=telegram_file_id,
        txid=txid,
        status="pending",
    )
    db.add(receipt)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def approve_receipt(
    db: AsyncSession, receipt_id: str, admin_user_id: str | None, *, stack: bool = True
) -> tuple[PaymentReceipt, int]:
    receipt = await db.get(PaymentReceipt, receipt_id)
    if receipt is None or receipt.status == "approved":
        raise ValueError("receipt_not_pending")
    package = await db.get(Package, receipt.package_id) if receipt.package_id else None
    added = 0
    if package:
        await balance.add_package(db, receipt.user_id, package, stack=stack)
        added = package.ai_tokens
    receipt.status = "approved"
    receipt.reviewed_by = admin_user_id
    receipt.reviewed_at = utcnow()
    await db.commit()
    await db.refresh(receipt)
    return receipt, added


async def reject_receipt(
    db: AsyncSession, receipt_id: str, admin_user_id: str | None, note: str = ""
) -> PaymentReceipt:
    receipt = await db.get(PaymentReceipt, receipt_id)
    if receipt is None:
        raise ValueError("not_found")
    receipt.status = "rejected"
    receipt.admin_note = note
    receipt.reviewed_by = admin_user_id
    receipt.reviewed_at = utcnow()
    await db.commit()
    await db.refresh(receipt)
    return receipt
