"""Add Odoo request identity and durable creation claims.

Revision ID: 0003_odoo_terminal
Revises: 0002_integration_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_odoo_terminal"
down_revision = "0002_integration_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("api_clients", sa.Column("odoo_instance", sa.String(120), nullable=True))
    op.create_table(
        "odoo_payment_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("api_client_id", sa.Integer, sa.ForeignKey("api_clients.id"), nullable=False),
        sa.Column("instance", sa.String(120), nullable=False),
        sa.Column("request_reference", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("invoice_id", sa.String(80), nullable=False),
        sa.Column("invoice_number", sa.String(120), nullable=False),
        sa.Column("customer_id", sa.String(80), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("qr_collections.id"), unique=True),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("instance", "request_reference", name="uq_odoo_request_identity"),
        sa.CheckConstraint("state IN ('creating', 'ready', 'ambiguous')", name="ck_odoo_request_state"),
        sa.CheckConstraint("amount_paise >= 100", name="ck_odoo_request_amount"),
    )


def downgrade():
    op.drop_table("odoo_payment_requests")
    op.drop_column("api_clients", "odoo_instance")
