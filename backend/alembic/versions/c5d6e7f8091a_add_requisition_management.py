"""add_requisition_management

Revision ID: c5d6e7f8091a
Revises: b4c5d6e7f809
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8091a"
down_revision: Union[str, None] = "b4c5d6e7f809"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "material_requisitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("mr_number", sa.String(length=50), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("needed_by_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_material_requisitions_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_material_requisitions_requested_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_requisitions"),
        sa.UniqueConstraint(
            "company_id",
            "mr_number",
            name="uq_material_requisitions_company_mr_number",
        ),
    )
    op.create_index(
        "ix_material_requisitions_company_id",
        "material_requisitions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_mr_number",
        "material_requisitions",
        ["mr_number"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_requested_by_user_id",
        "material_requisitions",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_department_id",
        "material_requisitions",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_status",
        "material_requisitions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_priority",
        "material_requisitions",
        ["priority"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisitions_needed_by_date",
        "material_requisitions",
        ["needed_by_date"],
        unique=False,
    )

    op.create_table(
        "material_requisition_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("material_requisition_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_code", sa.String(length=100), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("unit_code", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column(
            "estimated_unit_cost",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
        sa.Column("currency_id", sa.Integer(), nullable=True),
        sa.Column(
            "estimated_unit_cost_base",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
        sa.Column("base_currency_id", sa.Integer(), nullable=True),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["base_currency_id"],
            ["currencies.id"],
            name="fk_material_requisition_items_base_currency_id_currencies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name="fk_material_requisition_items_currency_id_currencies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_material_requisition_items_item_id_items",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["material_requisition_id"],
            ["material_requisitions.id"],
            name="fk_mr_items_requisition_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="fk_material_requisition_items_unit_id_units",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_requisition_items"),
    )
    op.create_index(
        "ix_material_requisition_items_material_requisition_id",
        "material_requisition_items",
        ["material_requisition_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_item_id",
        "material_requisition_items",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_unit_id",
        "material_requisition_items",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_currency_id",
        "material_requisition_items",
        ["currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_base_currency_id",
        "material_requisition_items",
        ["base_currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_item_code",
        "material_requisition_items",
        ["item_code"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_items_item_name",
        "material_requisition_items",
        ["item_name"],
        unique=False,
    )

    op.create_table(
        "material_requisition_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("material_requisition_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name="fk_material_requisition_status_history_changed_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["material_requisition_id"],
            ["material_requisitions.id"],
            name="fk_mr_history_requisition_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_material_requisition_status_history",
        ),
    )
    op.create_index(
        "ix_material_requisition_status_history_material_requisition_id",
        "material_requisition_status_history",
        ["material_requisition_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_status_history_changed_by_user_id",
        "material_requisition_status_history",
        ["changed_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_material_requisition_status_history_to_status",
        "material_requisition_status_history",
        ["to_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_requisition_status_history_to_status",
        table_name="material_requisition_status_history",
    )
    op.drop_index(
        "ix_material_requisition_status_history_changed_by_user_id",
        table_name="material_requisition_status_history",
    )
    op.drop_index(
        "ix_material_requisition_status_history_material_requisition_id",
        table_name="material_requisition_status_history",
    )
    op.drop_table("material_requisition_status_history")

    op.drop_index(
        "ix_material_requisition_items_item_name",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_item_code",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_base_currency_id",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_currency_id",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_unit_id",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_item_id",
        table_name="material_requisition_items",
    )
    op.drop_index(
        "ix_material_requisition_items_material_requisition_id",
        table_name="material_requisition_items",
    )
    op.drop_table("material_requisition_items")

    op.drop_index(
        "ix_material_requisitions_needed_by_date",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_priority",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_status",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_department_id",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_requested_by_user_id",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_mr_number",
        table_name="material_requisitions",
    )
    op.drop_index(
        "ix_material_requisitions_company_id",
        table_name="material_requisitions",
    )
    op.drop_table("material_requisitions")
