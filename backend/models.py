import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_public_token() -> str:
    """Unguessable token for the public payment page URL (256 bits, 43 URL-safe characters)."""
    return secrets.token_urlsafe(32)


TS = DateTime(timezone=True)


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
    __table_args__ = (
        # Idempotency keys are scoped to the API client that sent them.
        UniqueConstraint("api_client_id", "idempotency_key", name="uq_qr_collections_client_idempotency_key"),
        CheckConstraint("source IN ('dashboard', 'api')", name="ck_qr_collections_source"),
        CheckConstraint("(source = 'api') = (api_client_id IS NOT NULL)", name="ck_qr_collections_source_client"),
        CheckConstraint("idempotency_key IS NULL OR api_client_id IS NOT NULL",
                        name="ck_qr_collections_idempotency_needs_client"),
        CheckConstraint("amount_paise > 0", name="ck_qr_collections_amount_positive"),
        CheckConstraint("amount_received_paise >= 0", name="ck_qr_collections_received_nonnegative"),
    )
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
    # Added in 0002
    public_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=new_public_token)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="dashboard", server_default="dashboard")
    api_client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_clients.id"), nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # SHA-256 of the normalised request, so a reused key with a different request can be refused.
    idempotency_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, onupdate=utcnow,
                                                 server_default=text("now()"))

    created_by: Mapped[User] = relationship()
    api_client: Mapped[Optional["ApiClient"]] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="collection", order_by="Payment.first_seen_at")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_paise >= 0", name="ck_payments_amount_nonnegative"),)
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
    __table_args__ = (Index("ix_webhook_events_status_received_at", "status", "received_at"),)
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


class ApiClient(Base):
    """An external system (e.g. Odoo later) allowed to call the payment API.

    The API key itself is never stored: only key_prefix (to find the row) and key_hash.
    callback_secret_encrypted holds the callback signing secret encrypted with an app key
    (it must be recoverable to sign callbacks, so it is encrypted rather than hashed).
    """
    __tablename__ = "api_clients"
    __table_args__ = (
        CheckConstraint("environment IN ('test', 'live')", name="ck_api_clients_environment"),
        CheckConstraint("callback_url IS NULL OR callback_url LIKE 'https://%'", name="ck_api_clients_callback_https"),
        CheckConstraint("revoked_at IS NULL OR is_active = false", name="ck_api_clients_revoked_inactive"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(10), nullable=False)
    callback_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    callback_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, onupdate=utcnow,
                                                 server_default=text("now()"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)


CALLBACK_STATUSES = ("pending", "delivering", "delivered", "failed", "abandoned")


class CallbackDelivery(Base):
    """Outbox row: one notification to one API client about one status change of a payment request.

    Written in the same transaction as the status change, so a crash cannot lose it. event_id is sent
    to the receiver so it can drop repeats; the unique constraint stops the same change being queued twice.
    """
    __tablename__ = "callback_deliveries"
    __table_args__ = (
        UniqueConstraint("collection_id", "api_client_id", "event_type", name="uq_callback_deliveries_transition"),
        CheckConstraint("status IN ('pending', 'delivering', 'delivered', 'failed', 'abandoned')",
                        name="ck_callback_deliveries_status"),
        CheckConstraint("attempts >= 0", name="ck_callback_deliveries_attempts_nonnegative"),
        CheckConstraint("target_url LIKE 'https://%'", name="ck_callback_deliveries_target_https"),
        Index("ix_callback_deliveries_due", "status", "next_attempt_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    api_client_id: Mapped[int] = mapped_column(ForeignKey("api_clients.id"), nullable=False, index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("qr_collections.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    next_attempt_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, server_default=text("now()"))
    # Lease: a worker owns the row until this time; if it crashes, the row becomes due again.
    locked_until: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    last_response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, onupdate=utcnow,
                                                 server_default=text("now()"))

    attempts_log: Mapped[list["CallbackAttempt"]] = relationship(
        back_populates="delivery", order_by="CallbackAttempt.attempt_no", cascade="all, delete-orphan")


class CallbackAttempt(Base):
    __tablename__ = "callback_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "attempt_no", name="uq_callback_attempts_delivery_attempt"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("callback_deliveries.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, server_default=text("now()"))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    delivery: Mapped[CallbackDelivery] = relationship(back_populates="attempts_log")


class AuditLog(Base):
    """Append-only record of who did what. The database rejects UPDATE and DELETE (see migration 0002)."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'api_client', 'system', 'razorpay')", name="ck_audit_logs_actor_type"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, server_default=text("now()"),
                                                  index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_api_client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_clients.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
