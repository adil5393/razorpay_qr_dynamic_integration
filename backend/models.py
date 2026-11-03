from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class QRCollection(Base):
    __tablename__ = "qr_collections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    razorpay_qr_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    reference: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    qr_status: Mapped[str] = mapped_column(String(20), nullable=False)
    close_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    close_by: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_received_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by: Mapped[User] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="collection", order_by="Payment.first_seen_at")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    collection_id: Mapped[int] = mapped_column(ForeignKey("qr_collections.id"), nullable=False, index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    vpa: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rzp_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    collection: Mapped[QRCollection] = relationship(back_populates="payments")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    razorpay_qr_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    collection_id: Mapped[Optional[int]] = mapped_column(ForeignKey("qr_collections.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    identifier: Mapped[str] = mapped_column(String(320), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
