"""phase_0.2 — purchase_management (drop buying_management, create purchase tables)

PRECONDITION: a1_phase_0_3_currency must be applied first (currencies table required for FKs).

Revision ID: a2_phase_0_2_purchase
Revises: a1_phase_0_3_currency
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_phase_0_2_purchase"
down_revision: Union[str, None] = "a1_phase_0_3_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Drop old buying_management tables (safe — no FK from other modules) ─
    op.drop_table("buying_process_receipt_links")
    op.drop_table("buying_process_costs")
    op.drop_table("buying_process_items")
    op.drop_table("buying_processes")

    # ── 2. Create purchase_orders ──────────────────────────────────────────────
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_number", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("base_currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_rate_used", sa.Numeric(28, 10), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text(), nullable=True),
        # description_embedding (vector(1024)) is added below via raw SQL — pgvector type not in SA core
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("company_id", "reference_number", name="uq_po_company_reference"),
    )

    # Re-create description_embedding column properly using raw SQL (pgvector type)
    op.execute("ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS description_embedding vector(1024)")

    op.create_index("ix_purchase_orders_company_id", "purchase_orders", ["company_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])
    op.create_index("ix_purchase_orders_approval_status", "purchase_orders", ["approval_status"])
    op.create_index("ix_purchase_orders_reference_number", "purchase_orders", ["reference_number"])
    op.create_index("ix_purchase_orders_supplier_name", "purchase_orders", ["supplier_name"])

    # ── 3. Create purchase_phases ──────────────────────────────────────────────
    op.create_table(
        "purchase_phases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("exchange_rate_used", sa.Numeric(28, 10), nullable=True),
        sa.Column("expected_delivery_date", sa.DateTime(), nullable=True),
        sa.Column("actual_delivery_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_purchase_phases_purchase_order_id", "purchase_phases", ["purchase_order_id"])
    op.create_index("ix_purchase_phases_status", "purchase_phases", ["status"])

    # ── 4. Create purchase_phase_items ─────────────────────────────────────────
    op.create_table(
        "purchase_phase_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phase_id", sa.Integer(), sa.ForeignKey("purchase_phases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_name", sa.String(255), nullable=False),
        sa.Column("item_code", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False, server_default="pcs"),
        sa.Column("unit_price", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("unit_price_base", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("base_currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_rate_used", sa.Numeric(28, 10), nullable=False, server_default="1"),
        sa.Column("line_total", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("line_total_base", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_purchase_phase_items_phase_id", "purchase_phase_items", ["phase_id"])
    op.create_index("ix_purchase_phase_items_item_code", "purchase_phase_items", ["item_code"])

    # ── 5. Create purchase_order_costs ─────────────────────────────────────────
    op.create_table(
        "purchase_order_costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cost_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(28, 10), nullable=False),
        sa.Column("currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_base", sa.Numeric(28, 10), nullable=False),
        sa.Column("base_currency_id", sa.Integer(), sa.ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exchange_rate_used", sa.Numeric(28, 10), nullable=False, server_default="1"),
        sa.Column("allocation_method", sa.String(20), nullable=False, server_default="per_value"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_purchase_order_costs_purchase_order_id", "purchase_order_costs", ["purchase_order_id"])

    # ── 6. Create purchase_order_receipt_links ─────────────────────────────────
    op.create_table(
        "purchase_order_receipt_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("financial_receipt_id", sa.Integer(), nullable=False),  # plain ID, no FK import
        sa.Column("linked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("linked_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_po_receipt_links_purchase_order_id", "purchase_order_receipt_links", ["purchase_order_id"])
    op.create_index("ix_po_receipt_links_financial_receipt_id", "purchase_order_receipt_links", ["financial_receipt_id"])

    # ── 7. Seed RBAC permissions ───────────────────────────────────────────────
    from sqlalchemy.orm import Session
    from db.seed_rbac import get_or_create_permission
    from purchase_management.permissions import PERMISSIONS

    bind = op.get_bind()
    session = Session(bind=bind)
    for name, resource, action, description in PERMISSIONS:
        get_or_create_permission(session, name, resource, action, description)
    session.commit()


def downgrade() -> None:
    op.drop_index("ix_po_receipt_links_financial_receipt_id", table_name="purchase_order_receipt_links")
    op.drop_index("ix_po_receipt_links_purchase_order_id", table_name="purchase_order_receipt_links")
    op.drop_table("purchase_order_receipt_links")
    op.drop_index("ix_purchase_order_costs_purchase_order_id", table_name="purchase_order_costs")
    op.drop_table("purchase_order_costs")
    op.drop_index("ix_purchase_phase_items_phase_id", table_name="purchase_phase_items")
    op.drop_table("purchase_phase_items")
    op.drop_index("ix_purchase_phases_purchase_order_id", table_name="purchase_phases")
    op.drop_table("purchase_phases")
    op.drop_index("ix_purchase_orders_company_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    # Note: buying_management tables are NOT recreated in downgrade — this was a clean replacement.
