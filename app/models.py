"""SQLAlchemy models — the full schema from the design doc (SQLite-friendly).

UUID primary keys are stored as 32-char hex strings so the same schema
migrates cleanly to PostgreSQL later.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, new_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    telegram_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="fa")
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    status: Mapped[str] = mapped_column(String(16), default="active")
    default_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unrestricted_usage: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_privacy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[float] = mapped_column(Float)
    price_toman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_tokens: Mapped[int] = mapped_column(Integer)
    validity_days: Mapped[int] = mapped_column(Integer, default=30)
    allowed_modes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserBalance(Base):
    __tablename__ = "user_balances"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def remaining(self) -> int:
        return max(0, self.total_tokens - self.used_tokens)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp < utcnow()


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    type: Mapped[str] = mapped_column(String(32))  # card|sheba|btc|usdt_trc20|...
    display_name: Mapped[str] = mapped_column(String(255))
    encrypted_value: Mapped[str] = mapped_column(Text)  # encrypted card/sheba/wallet
    network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    package_id: Mapped[str | None] = mapped_column(ForeignKey("packages.id"), nullable=True)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_user_paid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    txid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIMode(Base):
    __tablename__ = "ai_modes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    fa_name: Mapped[str] = mapped_column(String(255))
    en_name: Mapped[str] = mapped_column(String(255))
    description_fa: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(128))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    supports_text: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_image_input: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_image_output: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_file_input: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_research: Mapped[bool] = mapped_column(Boolean, default=False)
    base_credit_cost: Mapped[int] = mapped_column(Integer, default=0)
    input_token_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    output_token_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    reasoning_token_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    tool_call_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    markup_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    max_file_size_mb: Mapped[int] = mapped_column(Integer, default=15)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    current_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned_facts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    charged_ai_tokens: Mapped[int] = mapped_column(Integer, default=0)
    api_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    api_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    charged_ai_tokens: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class FileAsset(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    openai_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="document")  # document|image|receipt|output
    status: Mapped[str] = mapped_column(String(16), default="stored")
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProviderApiKey(Base):
    __tablename__ = "provider_api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    name: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    daily_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    admin_id: Mapped[int] = mapped_column(Integer)  # telegram id
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminChatAccessLog(Base):
    __tablename__ = "admin_chat_access_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    admin_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(32))  # view|export|backup|delete
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
