"""add_rfq_management

Revision ID: d6e7f8091a2b
Revises: c5d6e7f8091a
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8091a2b"
down_revision: Union[str, None] = "c5d6e7f8091a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rfqs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("rfq_number", sa.String(length=50), nullable=False),
        sa.Column("mr_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deadline_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_rfqs_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mr_id"],
            ["material_requisitions.id"],
            name="fk_rfqs_mr",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_rfqs_creator",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rfqs"),
        sa.UniqueConstraint(
            "company_id",
            "rfq_number",
            name="uq_rfqs_company_number",
        ),
        sa.UniqueConstraint(
            "company_id",
            "mr_id",
            name="uq_rfqs_company_mr",
        ),
    )
    op.create_index("ix_rfqs_company_id", "rfqs", ["company_id"], unique=False)
    op.create_index("ix_rfqs_rfq_number", "rfqs", ["rfq_number"], unique=False)
    op.create_index("ix_rfqs_mr_id", "rfqs", ["mr_id"], unique=False)
    op.create_index("ix_rfqs_status", "rfqs", ["status"], unique=False)
    op.create_index("ix_rfqs_deadline_date", "rfqs", ["deadline_date"], unique=False)
    op.create_index(
        "ix_rfqs_created_by_user_id",
        "rfqs",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "rfq_suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_code", sa.String(length=50), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("response_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rfq_id"],
            ["rfqs.id"],
            name="fk_rfq_suppliers_rfq",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_rfq_suppliers_supplier",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rfq_suppliers"),
        sa.UniqueConstraint(
            "rfq_id",
            "supplier_id",
            name="uq_rfq_suppliers_rfq_supplier",
        ),
    )
    op.create_index("ix_rfq_suppliers_rfq_id", "rfq_suppliers", ["rfq_id"], unique=False)
    op.create_index(
        "ix_rfq_suppliers_supplier_id",
        "rfq_suppliers",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "ix_rfq_suppliers_response_status",
        "rfq_suppliers",
        ["response_status"],
        unique=False,
    )

    op.create_table(
        "rfq_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_code", sa.String(length=100), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("unit_code", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("specifications", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rfq_id"],
            ["rfqs.id"],
            name="fk_rfq_items_rfq",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_rfq_items_item",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="fk_rfq_items_unit",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rfq_items"),
    )
    op.create_index("ix_rfq_items_rfq_id", "rfq_items", ["rfq_id"], unique=False)
    op.create_index("ix_rfq_items_item_id", "rfq_items", ["item_id"], unique=False)
    op.create_index("ix_rfq_items_unit_id", "rfq_items", ["unit_id"], unique=False)
    op.create_index("ix_rfq_items_item_code", "rfq_items", ["item_code"], unique=False)
    op.create_index("ix_rfq_items_item_name", "rfq_items", ["item_name"], unique=False)

    op.create_table(
        "quotation_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_code", sa.String(length=50), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("payment_terms", sa.Text(), nullable=True),
        sa.Column("delivery_days", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_winner", sa.Boolean(), nullable=False),
        sa.Column("selected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("selected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rfq_id"],
            ["rfqs.id"],
            name="fk_quote_responses_rfq",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_quote_responses_supplier",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["selected_by_user_id"],
            ["users.id"],
            name="fk_quote_responses_selected_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quote_responses"),
        sa.UniqueConstraint(
            "rfq_id",
            "supplier_id",
            name="uq_quote_responses_rfq_supplier",
        ),
    )
    op.create_index(
        "ix_quote_responses_rfq_id",
        "quotation_responses",
        ["rfq_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_responses_supplier_id",
        "quotation_responses",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_responses_is_winner",
        "quotation_responses",
        ["is_winner"],
        unique=False,
    )
    op.create_index(
        "ix_quote_responses_received_at",
        "quotation_responses",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        "ix_quote_responses_valid_until",
        "quotation_responses",
        ["valid_until"],
        unique=False,
    )

    op.create_table(
        "quotation_response_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quotation_response_id", sa.Integer(), nullable=False),
        sa.Column("rfq_item_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("unit_price_base", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("base_currency_id", sa.Integer(), nullable=False),
        sa.Column("exchange_rate_used", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["quotation_response_id"],
            ["quotation_responses.id"],
            name="fk_quote_items_response",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_item_id"],
            ["rfq_items.id"],
            name="fk_quote_items_rfq_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name="fk_quote_items_currency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_currency_id"],
            ["currencies.id"],
            name="fk_quote_items_base_currency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quote_response_items"),
        sa.UniqueConstraint(
            "quotation_response_id",
            "rfq_item_id",
            name="uq_quote_items_response_rfq_item",
        ),
    )
    op.create_index(
        "ix_quote_items_response_id",
        "quotation_response_items",
        ["quotation_response_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_items_rfq_item_id",
        "quotation_response_items",
        ["rfq_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_items_currency_id",
        "quotation_response_items",
        ["currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_quote_items_base_currency_id",
        "quotation_response_items",
        ["base_currency_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quote_items_base_currency_id", table_name="quotation_response_items")
    op.drop_index("ix_quote_items_currency_id", table_name="quotation_response_items")
    op.drop_index("ix_quote_items_rfq_item_id", table_name="quotation_response_items")
    op.drop_index("ix_quote_items_response_id", table_name="quotation_response_items")
    op.drop_table("quotation_response_items")

    op.drop_index("ix_quote_responses_valid_until", table_name="quotation_responses")
    op.drop_index("ix_quote_responses_received_at", table_name="quotation_responses")
    op.drop_index("ix_quote_responses_is_winner", table_name="quotation_responses")
    op.drop_index("ix_quote_responses_supplier_id", table_name="quotation_responses")
    op.drop_index("ix_quote_responses_rfq_id", table_name="quotation_responses")
    op.drop_table("quotation_responses")

    op.drop_index("ix_rfq_items_item_name", table_name="rfq_items")
    op.drop_index("ix_rfq_items_item_code", table_name="rfq_items")
    op.drop_index("ix_rfq_items_unit_id", table_name="rfq_items")
    op.drop_index("ix_rfq_items_item_id", table_name="rfq_items")
    op.drop_index("ix_rfq_items_rfq_id", table_name="rfq_items")
    op.drop_table("rfq_items")

    op.drop_index("ix_rfq_suppliers_response_status", table_name="rfq_suppliers")
    op.drop_index("ix_rfq_suppliers_supplier_id", table_name="rfq_suppliers")
    op.drop_index("ix_rfq_suppliers_rfq_id", table_name="rfq_suppliers")
    op.drop_table("rfq_suppliers")

    op.drop_index("ix_rfqs_created_by_user_id", table_name="rfqs")
    op.drop_index("ix_rfqs_deadline_date", table_name="rfqs")
    op.drop_index("ix_rfqs_status", table_name="rfqs")
    op.drop_index("ix_rfqs_mr_id", table_name="rfqs")
    op.drop_index("ix_rfqs_rfq_number", table_name="rfqs")
    op.drop_index("ix_rfqs_company_id", table_name="rfqs")
    op.drop_table("rfqs")
