"""add_goods_receipt_management

Revision ID: e7f8091a2b3c
Revises: d6e7f8091a2b
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8091a2b3c"
down_revision: Union[str, None] = "d6e7f8091a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_phase_items",
        sa.Column(
            "received_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column(
        "purchase_phase_items",
        "received_quantity",
        server_default=None,
    )

    op.create_table(
        "goods_receipt_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("grn_number", sa.String(length=50), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_phase_id", sa.Integer(), nullable=False),
        sa.Column("received_by_user_id", sa.Integer(), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("delivery_note_number", sa.String(length=100), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_grn_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name="fk_grn_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_phase_id"],
            ["purchase_phases.id"],
            name="fk_grn_phase",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_user_id"],
            ["users.id"],
            name="fk_grn_receiver",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goods_receipt_notes"),
        sa.UniqueConstraint(
            "company_id",
            "grn_number",
            name="uq_grn_company_number",
        ),
    )

    for name, columns in [
        ("ix_grn_company_id", ["company_id"]),
        ("ix_grn_number", ["grn_number"]),
        ("ix_grn_purchase_order_id", ["purchase_order_id"]),
        ("ix_grn_purchase_phase_id", ["purchase_phase_id"]),
        ("ix_grn_received_by_user_id", ["received_by_user_id"]),
        ("ix_grn_receipt_date", ["receipt_date"]),
        ("ix_grn_status", ["status"]),
        ("ix_grn_delivery_note_number", ["delivery_note_number"]),
    ]:
        op.create_index(name, "goods_receipt_notes", columns, unique=False)

    op.create_table(
        "goods_receipt_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_note_id", sa.Integer(), nullable=False),
        sa.Column("purchase_phase_item_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_code", sa.String(length=100), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("unit_code", sa.String(length=30), nullable=False),
        sa.Column(
            "received_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "accepted_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "rejected_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("storage_location_id", sa.Integer(), nullable=True),
        sa.Column(
            "unit_cost",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "unit_cost_base",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("base_currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["goods_receipt_note_id"],
            ["goods_receipt_notes.id"],
            name="fk_grn_items_grn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_phase_item_id"],
            ["purchase_phase_items.id"],
            name="fk_grn_items_phase_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_grn_items_item",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name="fk_grn_items_currency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_currency_id"],
            ["currencies.id"],
            name="fk_grn_items_base_currency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goods_receipt_items"),
        sa.UniqueConstraint(
            "goods_receipt_note_id",
            "purchase_phase_item_id",
            name="uq_grn_items_phase_item",
        ),
    )

    for name, columns in [
        ("ix_grn_items_grn_id", ["goods_receipt_note_id"]),
        ("ix_grn_items_phase_item_id", ["purchase_phase_item_id"]),
        ("ix_grn_items_item_id", ["item_id"]),
        ("ix_grn_items_storage_location_id", ["storage_location_id"]),
        ("ix_grn_items_currency_id", ["currency_id"]),
        ("ix_grn_items_base_currency_id", ["base_currency_id"]),
    ]:
        op.create_index(name, "goods_receipt_items", columns, unique=False)


def downgrade() -> None:
    for name in [
        "ix_grn_items_base_currency_id",
        "ix_grn_items_currency_id",
        "ix_grn_items_storage_location_id",
        "ix_grn_items_item_id",
        "ix_grn_items_phase_item_id",
        "ix_grn_items_grn_id",
    ]:
        op.drop_index(name, table_name="goods_receipt_items")

    op.drop_table("goods_receipt_items")

    for name in [
        "ix_grn_delivery_note_number",
        "ix_grn_status",
        "ix_grn_receipt_date",
        "ix_grn_received_by_user_id",
        "ix_grn_purchase_phase_id",
        "ix_grn_purchase_order_id",
        "ix_grn_number",
        "ix_grn_company_id",
    ]:
        op.drop_index(name, table_name="goods_receipt_notes")

    op.drop_table("goods_receipt_notes")
    op.drop_column("purchase_phase_items", "received_quantity")
