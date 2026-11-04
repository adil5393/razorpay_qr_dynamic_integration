"""integration foundation: public tokens, API clients, idempotency, callback outbox, audit log

Revision ID: 0002_integration_foundation
Revises: 0001_initial
Create Date: 2026-11-04

Additive only. Existing rows are kept unchanged; new qr_collections columns are filled in for them:
  public_token -> a new random token per row
  source       -> 'dashboard' (everything before this migration came from the dashboard)
  updated_at   -> last_synced_at, or created_at if never synced
"""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0002_integration_foundation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade():
    # ---------- api_clients ----------
    op.create_table(
        "api_clients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("environment", sa.String(10), nullable=False),
        sa.Column("callback_url", sa.Text, nullable=True),
        sa.Column("callback_secret_encrypted", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.CheckConstraint("environment IN ('test', 'live')", name="ck_api_clients_environment"),
        sa.CheckConstraint("callback_url IS NULL OR callback_url LIKE 'https://%'", name="ck_api_clients_callback_https"),
        sa.CheckConstraint("revoked_at IS NULL OR is_active = false", name="ck_api_clients_revoked_inactive"),
    )

    # ---------- qr_collections: new columns ----------
    op.add_column("qr_collections", sa.Column("public_token", sa.String(64), nullable=True))
    op.add_column("qr_collections", sa.Column("source", sa.String(20), nullable=False, server_default="dashboard"))
    op.add_column("qr_collections", sa.Column("api_client_id", sa.Integer, nullable=True))
    op.add_column("qr_collections", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("qr_collections", sa.Column("idempotency_fingerprint", sa.String(64), nullable=True))
    op.add_column("qr_collections", sa.Column("updated_at", TS, nullable=True))

    conn = op.get_bind()
    ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM qr_collections WHERE public_token IS NULL"))]
    for cid in ids:
        conn.execute(sa.text("UPDATE qr_collections SET public_token = :t WHERE id = :id"),
                     {"t": secrets.token_urlsafe(32), "id": cid})
    conn.execute(sa.text("UPDATE qr_collections SET updated_at = COALESCE(last_synced_at, created_at) WHERE updated_at IS NULL"))

    op.alter_column("qr_collections", "public_token", nullable=False)
    op.alter_column("qr_collections", "updated_at", nullable=False, server_default=NOW)
    op.create_unique_constraint("qr_collections_public_token_key", "qr_collections", ["public_token"])
    op.create_foreign_key("qr_collections_api_client_id_fkey", "qr_collections", "api_clients", ["api_client_id"], ["id"])
    op.create_index("ix_qr_collections_api_client_id", "qr_collections", ["api_client_id"])
    op.create_unique_constraint("uq_qr_collections_client_idempotency_key", "qr_collections",
                                ["api_client_id", "idempotency_key"])
    op.create_check_constraint("ck_qr_collections_source", "qr_collections", "source IN ('dashboard', 'api')")
    op.create_check_constraint("ck_qr_collections_source_client", "qr_collections",
                               "(source = 'api') = (api_client_id IS NOT NULL)")
    op.create_check_constraint("ck_qr_collections_idempotency_needs_client", "qr_collections",
                               "idempotency_key IS NULL OR api_client_id IS NOT NULL")
    op.create_check_constraint("ck_qr_collections_amount_positive", "qr_collections", "amount_paise > 0")
    op.create_check_constraint("ck_qr_collections_received_nonnegative", "qr_collections", "amount_received_paise >= 0")

    # ---------- payments / webhook_events ----------
    op.create_check_constraint("ck_payments_amount_nonnegative", "payments", "amount_paise >= 0")
    op.create_index("ix_webhook_events_status_received_at", "webhook_events", ["status", "received_at"])

    # ---------- callback outbox ----------
    op.create_table(
        "callback_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("api_client_id", sa.Integer, sa.ForeignKey("api_clients.id"), nullable=False),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("qr_collections.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("target_url", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="12"),
        sa.Column("next_attempt_at", TS, nullable=False, server_default=NOW),
        sa.Column("locked_until", TS, nullable=True),
        sa.Column("last_attempt_at", TS, nullable=True),
        sa.Column("last_response_status", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("delivered_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("collection_id", "api_client_id", "event_type", name="uq_callback_deliveries_transition"),
        sa.CheckConstraint("status IN ('pending', 'delivering', 'delivered', 'failed', 'abandoned')",
                           name="ck_callback_deliveries_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_callback_deliveries_attempts_nonnegative"),
        sa.CheckConstraint("target_url LIKE 'https://%'", name="ck_callback_deliveries_target_https"),
    )
    op.create_index("ix_callback_deliveries_api_client_id", "callback_deliveries", ["api_client_id"])
    op.create_index("ix_callback_deliveries_collection_id", "callback_deliveries", ["collection_id"])
    op.create_index("ix_callback_deliveries_due", "callback_deliveries", ["status", "next_attempt_at"])

    op.create_table(
        "callback_attempts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("delivery_id", sa.BigInteger, sa.ForeignKey("callback_deliveries.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("attempt_no", sa.Integer, nullable=False),
        sa.Column("started_at", TS, nullable=False, server_default=NOW),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.UniqueConstraint("delivery_id", "attempt_no", name="uq_callback_attempts_delivery_attempt"),
    )
    op.create_index("ix_callback_attempts_delivery_id", "callback_attempts", ["delivery_id"])

    # ---------- audit log (append-only) ----------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=NOW),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_api_client_id", sa.Integer, sa.ForeignKey("api_clients.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("details", sa.JSON, nullable=True),
        sa.CheckConstraint("actor_type IN ('user', 'api_client', 'system', 'razorpay')", name="ck_audit_logs_actor_type"),
    )
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_actor_api_client_id", "audit_logs", ["actor_api_client_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only (% not allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
    """)


def downgrade():
    # Removes only what 0002 added. Data in the new tables/columns is lost; 0001 data is untouched.
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_table("audit_logs")
    op.drop_table("callback_attempts")
    op.drop_table("callback_deliveries")
    op.drop_index("ix_webhook_events_status_received_at", table_name="webhook_events")
    op.drop_constraint("ck_payments_amount_nonnegative", "payments", type_="check")
    for name in ("ck_qr_collections_received_nonnegative", "ck_qr_collections_amount_positive",
                 "ck_qr_collections_idempotency_needs_client", "ck_qr_collections_source_client",
                 "ck_qr_collections_source"):
        op.drop_constraint(name, "qr_collections", type_="check")
    op.drop_constraint("uq_qr_collections_client_idempotency_key", "qr_collections", type_="unique")
    op.drop_index("ix_qr_collections_api_client_id", table_name="qr_collections")
    op.drop_constraint("qr_collections_api_client_id_fkey", "qr_collections", type_="foreignkey")
    op.drop_constraint("qr_collections_public_token_key", "qr_collections", type_="unique")
    for col in ("updated_at", "idempotency_fingerprint", "idempotency_key", "api_client_id", "source", "public_token"):
        op.drop_column("qr_collections", col)
    op.drop_table("api_clients")
