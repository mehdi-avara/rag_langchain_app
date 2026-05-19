"""add buying management

Revision ID: 4db0c6e2fb0a
Revises: 217014123a16
Create Date: 2026-05-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4db0c6e2fb0a"
down_revision: Union[str, None] = "217014123a16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "buying_processes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("supplier_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("exchange_rate_to_base", sa.Numeric(18, 6), nullable=False),
        sa.Column("purchase_date", sa.DateTime(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("affects_warehouse", sa.Boolean(), nullable=False),
        sa.Column("warehouse_applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_buying_processes_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_buying_processes_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buying_processes")),
    )
    op.create_index("ix_buying_processes_company_id", "buying_processes", ["company_id"], unique=False)
    op.create_index("ix_buying_processes_owner_id", "buying_processes", ["owner_id"], unique=False)
    op.create_index("ix_buying_processes_purchase_date", "buying_processes", ["purchase_date"], unique=False)
    op.create_index("ix_buying_processes_status", "buying_processes", ["status"], unique=False)
    op.create_index(op.f("ix_buying_processes_title"), "buying_processes", ["title"], unique=False)
    op.create_index(op.f("ix_buying_processes_supplier_name"), "buying_processes", ["supplier_name"], unique=False)

    op.create_table(
        "buying_process_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("buying_process_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("exchange_rate_to_base", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("line_total_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("allocated_cost_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("final_unit_cost_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["buying_process_id"], ["buying_processes.id"], name=op.f("fk_buying_process_items_buying_process_id_buying_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["managed_models.id"], name=op.f("fk_buying_process_items_model_id_managed_models"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buying_process_items")),
    )
    op.create_index("ix_buying_process_items_buying_process_id", "buying_process_items", ["buying_process_id"], unique=False)
    op.create_index("ix_buying_process_items_model_id", "buying_process_items", ["model_id"], unique=False)
    op.create_index(op.f("ix_buying_process_items_color"), "buying_process_items", ["color"], unique=False)

    op.create_table(
        "buying_process_receipt_links",
        sa.Column("buying_process_id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("linked_by_user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["buying_process_id"], ["buying_processes.id"], name=op.f("fk_buying_process_receipt_links_buying_process_id_buying_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by_user_id"], ["users.id"], name=op.f("fk_buying_process_receipt_links_linked_by_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receipt_id"], ["financial_receipts.id"], name=op.f("fk_buying_process_receipt_links_receipt_id_financial_receipts"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("buying_process_id", "receipt_id", name=op.f("pk_buying_process_receipt_links")),
    )
    op.create_index("ix_buying_process_receipt_links_buying_process_id", "buying_process_receipt_links", ["buying_process_id"], unique=False)
    op.create_index("ix_buying_process_receipt_links_receipt_id", "buying_process_receipt_links", ["receipt_id"], unique=False)

    op.create_table(
        "buying_process_costs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("buying_process_id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=True),
        sa.Column("cost_type", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("exchange_rate_to_base", sa.Numeric(18, 6), nullable=False),
        sa.Column("amount_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("allocation_method", sa.String(), nullable=False),
        sa.Column("manual_allocations_json", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["buying_process_id"], ["buying_processes.id"], name=op.f("fk_buying_process_costs_buying_process_id_buying_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receipt_id"], ["financial_receipts.id"], name=op.f("fk_buying_process_costs_receipt_id_financial_receipts"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buying_process_costs")),
    )
    op.create_index("ix_buying_process_costs_buying_process_id", "buying_process_costs", ["buying_process_id"], unique=False)
    op.create_index("ix_buying_process_costs_receipt_id", "buying_process_costs", ["receipt_id"], unique=False)
    op.create_index("ix_buying_process_costs_cost_type", "buying_process_costs", ["cost_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_buying_process_costs_cost_type", table_name="buying_process_costs")
    op.drop_index("ix_buying_process_costs_receipt_id", table_name="buying_process_costs")
    op.drop_index("ix_buying_process_costs_buying_process_id", table_name="buying_process_costs")
    op.drop_table("buying_process_costs")

    op.drop_index("ix_buying_process_receipt_links_receipt_id", table_name="buying_process_receipt_links")
    op.drop_index("ix_buying_process_receipt_links_buying_process_id", table_name="buying_process_receipt_links")
    op.drop_table("buying_process_receipt_links")

    op.drop_index(op.f("ix_buying_process_items_color"), table_name="buying_process_items")
    op.drop_index("ix_buying_process_items_model_id", table_name="buying_process_items")
    op.drop_index("ix_buying_process_items_buying_process_id", table_name="buying_process_items")
    op.drop_table("buying_process_items")

    op.drop_index(op.f("ix_buying_processes_supplier_name"), table_name="buying_processes")
    op.drop_index(op.f("ix_buying_processes_title"), table_name="buying_processes")
    op.drop_index("ix_buying_processes_status", table_name="buying_processes")
    op.drop_index("ix_buying_processes_purchase_date", table_name="buying_processes")
    op.drop_index("ix_buying_processes_owner_id", table_name="buying_processes")
    op.drop_index("ix_buying_processes_company_id", table_name="buying_processes")
    op.drop_table("buying_processes")
