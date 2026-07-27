"""Add PO cost and payment data foundation.

Revision ID: 13c0a1b2d3e4
Revises: d3e4f5a6b7c8
Create Date: 2026-07-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "13c0a1b2d3e4"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "predicted_amount",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "predicted_currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "predicted_amount_base",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "predicted_exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_amount",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_amount_base",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_confirmed_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_order_costs",
        sa.Column(
            "actual_confirmed_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_purchase_order_costs_predicted_currency_id_currencies",
        "purchase_order_costs",
        "currencies",
        ["predicted_currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_purchase_order_costs_actual_currency_id_currencies",
        "purchase_order_costs",
        "currencies",
        ["actual_currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_purchase_order_costs_created_by_user_id_users",
        "purchase_order_costs",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        (
            "fk_purchase_order_costs_"
            "actual_confirmed_by_user_id_users"
        ),
        "purchase_order_costs",
        "users",
        ["actual_confirmed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_purchase_order_costs_predicted_currency_id",
        "purchase_order_costs",
        ["predicted_currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_costs_actual_currency_id",
        "purchase_order_costs",
        ["actual_currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_costs_created_by_user_id",
        "purchase_order_costs",
        ["created_by_user_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE purchase_order_costs
        SET
            predicted_amount = amount,
            predicted_currency_id = currency_id,
            predicted_amount_base = amount_base,
            predicted_exchange_rate_used =
                exchange_rate_used
        WHERE predicted_amount IS NULL
        """
    )

    op.create_check_constraint(
        "ck_purchase_order_costs_cost_type_valid",
        "purchase_order_costs",
        """
        cost_type IN (
            'goods',
            'freight',
            'customs',
            'tax',
            'insurance',
            'other'
        )
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_predicted_bundle",
        "purchase_order_costs",
        """
        (
            predicted_amount IS NULL
            AND predicted_currency_id IS NULL
            AND predicted_amount_base IS NULL
            AND predicted_exchange_rate_used IS NULL
        )
        OR
        (
            predicted_amount IS NOT NULL
            AND predicted_currency_id IS NOT NULL
            AND predicted_amount_base IS NOT NULL
            AND predicted_exchange_rate_used IS NOT NULL
        )
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_actual_bundle",
        "purchase_order_costs",
        """
        (
            actual_amount IS NULL
            AND actual_currency_id IS NULL
            AND actual_amount_base IS NULL
            AND actual_exchange_rate_used IS NULL
        )
        OR
        (
            actual_amount IS NOT NULL
            AND actual_currency_id IS NOT NULL
            AND actual_amount_base IS NOT NULL
            AND actual_exchange_rate_used IS NOT NULL
        )
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_predicted_amount_nonnegative",
        "purchase_order_costs",
        """
        predicted_amount IS NULL
        OR predicted_amount >= 0
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_actual_amount_nonnegative",
        "purchase_order_costs",
        """
        actual_amount IS NULL
        OR actual_amount >= 0
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_predicted_rate_positive",
        "purchase_order_costs",
        """
        predicted_exchange_rate_used IS NULL
        OR predicted_exchange_rate_used > 0
        """,
    )
    op.create_check_constraint(
        "ck_purchase_order_costs_actual_rate_positive",
        "purchase_order_costs",
        """
        actual_exchange_rate_used IS NULL
        OR actual_exchange_rate_used > 0
        """,
    )

    op.add_column(
        "financial_receipts",
        sa.Column(
            "currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "financial_receipts",
        sa.Column(
            "base_currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "financial_receipts",
        sa.Column(
            "amount_base",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )
    op.add_column(
        "financial_receipts",
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_financial_receipts_currency_id_currencies",
        "financial_receipts",
        "currencies",
        ["currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_financial_receipts_base_currency_id_currencies",
        "financial_receipts",
        "currencies",
        ["base_currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index(
        "ix_financial_receipts_currency_id",
        "financial_receipts",
        ["currency_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_receipts_base_currency_id",
        "financial_receipts",
        ["base_currency_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE financial_receipts AS receipt
        SET currency_id = currency.id
        FROM currencies AS currency
        WHERE UPPER(currency.code) =
              UPPER(receipt.currency)
        """
    )
    op.execute(
        """
        UPDATE financial_receipts AS receipt
        SET base_currency_id = currency.id
        FROM currencies AS currency
        WHERE UPPER(currency.code) =
              UPPER(receipt.base_currency)
        """
    )
    op.execute(
        """
        UPDATE financial_receipts
        SET
            amount_base = base_amount,
            exchange_rate_used =
                exchange_rate_to_base
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM financial_receipts
                WHERE currency_id IS NULL
                   OR base_currency_id IS NULL
                   OR amount_base IS NULL
                   OR exchange_rate_used IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Unable to normalize all financial receipt money fields';
            END IF;
        END
        $$;
        """
    )

    op.create_check_constraint(
        "ck_financial_receipts_canonical_money_bundle",
        "financial_receipts",
        """
        (
            currency_id IS NULL
            AND base_currency_id IS NULL
            AND amount_base IS NULL
            AND exchange_rate_used IS NULL
        )
        OR
        (
            currency_id IS NOT NULL
            AND base_currency_id IS NOT NULL
            AND amount_base IS NOT NULL
            AND exchange_rate_used IS NOT NULL
        )
        """,
    )
    op.create_check_constraint(
        "ck_financial_receipts_canonical_amount_base_nonnegative",
        "financial_receipts",
        """
        amount_base IS NULL
        OR amount_base >= 0
        """,
    )
    op.create_check_constraint(
        "ck_financial_receipts_canonical_rate_positive",
        "financial_receipts",
        """
        exchange_rate_used IS NULL
        OR exchange_rate_used > 0
        """,
    )

    op.add_column(
        "purchase_order_receipt_links",
        sa.Column(
            "allocation_status",
            sa.String(length=30),
            nullable=False,
            server_default="legacy_unallocated",
        ),
    )
    op.create_foreign_key(
        (
            'fk_po_receipt_links_receipt'
        ),
        "purchase_order_receipt_links",
        "financial_receipts",
        ["financial_receipt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_purchase_order_receipt_links_allocation_status",
        "purchase_order_receipt_links",
        "allocation_status = 'legacy_unallocated'",
    )
    op.alter_column(
        "purchase_order_receipt_links",
        "allocation_status",
        server_default=None,
    )

    op.create_table(
        "purchase_cost_payment_allocations",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "financial_receipt_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_cost_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "allocated_amount",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column(
            "currency_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "allocated_amount_base",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "allocated_amount > 0",
            name=(
                "ck_purchase_cost_payment_allocations_"
                "amount_positive"
            ),
        ),
        sa.CheckConstraint(
            "allocated_amount_base > 0",
            name=(
                "ck_purchase_cost_payment_allocations_"
                "amount_base_positive"
            ),
        ),
        sa.CheckConstraint(
            "exchange_rate_used > 0",
            name=(
                "ck_purchase_cost_payment_allocations_"
                "rate_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=(
                'fk_pcpa_company'
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["financial_receipt_id"],
            ["financial_receipts.id"],
            name=(
                'fk_pcpa_receipt'
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_cost_id"],
            ["purchase_order_costs.id"],
            name=(
                'fk_pcpa_cost'
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name=(
                'fk_pcpa_currency'
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=(
                'fk_pcpa_created_by'
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=(
                "pk_purchase_cost_payment_allocations"
            ),
        ),
    )

    op.create_index(
        "ix_purchase_cost_payment_allocations_company_id",
        "purchase_cost_payment_allocations",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        (
            "ix_purchase_cost_payment_allocations_"
            "financial_receipt_id"
        ),
        "purchase_cost_payment_allocations",
        ["financial_receipt_id"],
        unique=False,
    )
    op.create_index(
        (
            "ix_purchase_cost_payment_allocations_"
            "purchase_order_cost_id"
        ),
        "purchase_cost_payment_allocations",
        ["purchase_order_cost_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_cost_payment_allocations_currency_id",
        "purchase_cost_payment_allocations",
        ["currency_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_cost_payment_allocations_currency_id",
        table_name="purchase_cost_payment_allocations",
    )
    op.drop_index(
        (
            "ix_purchase_cost_payment_allocations_"
            "purchase_order_cost_id"
        ),
        table_name="purchase_cost_payment_allocations",
    )
    op.drop_index(
        (
            "ix_purchase_cost_payment_allocations_"
            "financial_receipt_id"
        ),
        table_name="purchase_cost_payment_allocations",
    )
    op.drop_index(
        "ix_purchase_cost_payment_allocations_company_id",
        table_name="purchase_cost_payment_allocations",
    )
    op.drop_table(
        "purchase_cost_payment_allocations"
    )

    op.drop_constraint(
        "ck_purchase_order_receipt_links_allocation_status",
        "purchase_order_receipt_links",
        type_="check",
    )
    op.drop_constraint(
        (
            'fk_po_receipt_links_receipt'
        ),
        "purchase_order_receipt_links",
        type_="foreignkey",
    )
    op.drop_column(
        "purchase_order_receipt_links",
        "allocation_status",
    )

    op.drop_constraint(
        "ck_financial_receipts_canonical_rate_positive",
        "financial_receipts",
        type_="check",
    )
    op.drop_constraint(
        (
            "ck_financial_receipts_"
            "canonical_amount_base_nonnegative"
        ),
        "financial_receipts",
        type_="check",
    )
    op.drop_constraint(
        "ck_financial_receipts_canonical_money_bundle",
        "financial_receipts",
        type_="check",
    )
    op.drop_index(
        "ix_financial_receipts_base_currency_id",
        table_name="financial_receipts",
    )
    op.drop_index(
        "ix_financial_receipts_currency_id",
        table_name="financial_receipts",
    )
    op.drop_constraint(
        (
            "fk_financial_receipts_"
            "base_currency_id_currencies"
        ),
        "financial_receipts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_financial_receipts_currency_id_currencies",
        "financial_receipts",
        type_="foreignkey",
    )
    op.drop_column(
        "financial_receipts",
        "exchange_rate_used",
    )
    op.drop_column(
        "financial_receipts",
        "amount_base",
    )
    op.drop_column(
        "financial_receipts",
        "base_currency_id",
    )
    op.drop_column(
        "financial_receipts",
        "currency_id",
    )

    op.drop_constraint(
        "ck_purchase_order_costs_actual_rate_positive",
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        (
            "ck_purchase_order_costs_"
            "predicted_rate_positive"
        ),
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        (
            "ck_purchase_order_costs_"
            "actual_amount_nonnegative"
        ),
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        (
            "ck_purchase_order_costs_"
            "predicted_amount_nonnegative"
        ),
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        "ck_purchase_order_costs_actual_bundle",
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        "ck_purchase_order_costs_predicted_bundle",
        "purchase_order_costs",
        type_="check",
    )
    op.drop_constraint(
        "ck_purchase_order_costs_cost_type_valid",
        "purchase_order_costs",
        type_="check",
    )

    op.drop_index(
        "ix_purchase_order_costs_created_by_user_id",
        table_name="purchase_order_costs",
    )
    op.drop_index(
        "ix_purchase_order_costs_actual_currency_id",
        table_name="purchase_order_costs",
    )
    op.drop_index(
        "ix_purchase_order_costs_predicted_currency_id",
        table_name="purchase_order_costs",
    )
    op.drop_constraint(
        (
            "fk_purchase_order_costs_"
            "actual_confirmed_by_user_id_users"
        ),
        "purchase_order_costs",
        type_="foreignkey",
    )
    op.drop_constraint(
        (
            "fk_purchase_order_costs_"
            "created_by_user_id_users"
        ),
        "purchase_order_costs",
        type_="foreignkey",
    )
    op.drop_constraint(
        (
            "fk_purchase_order_costs_"
            "actual_currency_id_currencies"
        ),
        "purchase_order_costs",
        type_="foreignkey",
    )
    op.drop_constraint(
        (
            "fk_purchase_order_costs_"
            "predicted_currency_id_currencies"
        ),
        "purchase_order_costs",
        type_="foreignkey",
    )

    op.drop_column(
        "purchase_order_costs",
        "actual_confirmed_by_user_id",
    )
    op.drop_column(
        "purchase_order_costs",
        "actual_confirmed_at",
    )
    op.drop_column(
        "purchase_order_costs",
        "created_by_user_id",
    )
    op.drop_column(
        "purchase_order_costs",
        "actual_exchange_rate_used",
    )
    op.drop_column(
        "purchase_order_costs",
        "actual_amount_base",
    )
    op.drop_column(
        "purchase_order_costs",
        "actual_currency_id",
    )
    op.drop_column(
        "purchase_order_costs",
        "actual_amount",
    )
    op.drop_column(
        "purchase_order_costs",
        "predicted_exchange_rate_used",
    )
    op.drop_column(
        "purchase_order_costs",
        "predicted_amount_base",
    )
    op.drop_column(
        "purchase_order_costs",
        "predicted_currency_id",
    )
    op.drop_column(
        "purchase_order_costs",
        "predicted_amount",
    )
