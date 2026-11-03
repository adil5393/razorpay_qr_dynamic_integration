"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("token_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_login_at", TS, nullable=True),
        sa.CheckConstraint("role IN ('admin','cashier')", name="ck_users_role"),
    )
    op.create_table(
        "qr_collections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("razorpay_qr_id", sa.String(64), nullable=False, unique=True),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(64), nullable=True),
        sa.Column("customer_name", sa.String(120), nullable=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("image_url", sa.Text, nullable=False),
        sa.Column("qr_status", sa.String(20), nullable=False),
        sa.Column("close_reason", sa.String(32), nullable=True),
        sa.Column("close_by", TS, nullable=True),
        sa.Column("closed_at", TS, nullable=True),
        sa.Column("payment_status", sa.String(20), nullable=False),
        sa.Column("paid_at", TS, nullable=True),
        sa.Column("amount_received_paise", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_synced_at", TS, nullable=True),
        sa.Column("last_sync_error", sa.Text, nullable=True),
        sa.CheckConstraint("amount_paise > 0", name="ck_qr_amount_positive"),
    )
    op.create_index("ix_qr_collections_reference", "qr_collections", ["reference"])
    op.create_index("ix_qr_collections_payment_status", "qr_collections", ["payment_status"])
    op.create_index("ix_qr_collections_created_by_id", "qr_collections", ["created_by_id"])
    op.create_index("ix_qr_collections_created_at", "qr_collections", ["created_at"])
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=False, unique=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("qr_collections.id"), nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("method", sa.String(20), nullable=True),
        sa.Column("vpa", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("contact", sa.String(32), nullable=True),
        sa.Column("is_successful", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error_description", sa.Text, nullable=True),
        sa.Column("rzp_created_at", TS, nullable=True),
        sa.Column("first_seen_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_payments_collection_id", "payments", ["collection_id"])
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=True, unique=True),
        sa.Column("event_type", sa.String(64), nullable=True),
        sa.Column("signature_valid", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("razorpay_qr_id", sa.String(64), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("qr_collections.id"), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("received_at", TS, nullable=False),
        sa.Column("processed_at", TS, nullable=True),
    )
    op.create_index("ix_webhook_events_razorpay_qr_id", "webhook_events", ["razorpay_qr_id"])
    op.create_table(
        "login_attempts",
        sa.Column("identifier", sa.String(320), primary_key=True),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", TS, nullable=True),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade():
    op.drop_table("login_attempts")
    op.drop_table("webhook_events")
    op.drop_table("payments")
    op.drop_table("qr_collections")
    op.drop_table("users")
