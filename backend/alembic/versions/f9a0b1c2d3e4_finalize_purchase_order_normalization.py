"""Finalize purchase-order normalization.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = (
    "e8f9a0b1c2d3"
)
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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_orders
                WHERE
                    rfq_id IS NOT NULL
                    AND source_material_requisition_id
                        IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order normalization blocked: an order has both RFQ and MR sources';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_orders
                WHERE rfq_id IS NOT NULL
                GROUP BY company_id, rfq_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order normalization blocked: duplicate company/RFQ sources exist';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_orders AS po
                LEFT JOIN quotation_responses
                    AS response
                  ON response.id =
                     po.winning_quotation_response_id
                WHERE
                    po.winning_quotation_response_id
                    IS NOT NULL
                    AND (
                        response.id IS NULL
                        OR response.rfq_id
                           IS DISTINCT FROM
                           po.rfq_id
                    )
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order normalization blocked: a winning quotation does not belong to its RFQ';
            END IF;
        END
        $$;
        """
    )

    op.drop_constraint(
        op.f(
            "ck_purchase_orders_"
            "ck_purchase_orders_single_source"
        ),
        "purchase_orders",
        type_="check",
    )
    op.drop_constraint(
        "uq_purchase_orders_company_rfq",
        "purchase_orders",
        type_="unique",
    )
    op.drop_index(
        "ix_purchase_orders_rfq_id",
        table_name="purchase_orders",
    )
    op.drop_constraint(
        "fk_purchase_orders_rfq",
        "purchase_orders",
        type_="foreignkey",
    )

    op.alter_column(
        "purchase_orders",
        "rfq_id",
        new_column_name="source_rfq_id",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )

    op.create_index(
        "ix_purchase_orders_source_rfq_id",
        "purchase_orders",
        ["source_rfq_id"],
    )
    op.create_foreign_key(
        "fk_purchase_orders_source_rfq",
        "purchase_orders",
        "rfqs",
        ["source_rfq_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_purchase_orders_company_source_rfq",
        "purchase_orders",
        [
            "company_id",
            "source_rfq_id",
        ],
    )
    op.create_check_constraint(
        "ck_purchase_orders_single_source",
        "purchase_orders",
        """
        NOT (
            source_rfq_id IS NOT NULL
            AND source_material_requisition_id
                IS NOT NULL
        )
        """,
    )

    op.drop_index(
        (
            "ix_purchase_orders_"
            "winning_quotation_response_id"
        ),
        table_name="purchase_orders",
    )
    op.drop_constraint(
        (
            "fk_purchase_orders_"
            "winning_quotation_response"
        ),
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_column(
        "purchase_orders",
        "winning_quotation_response_id",
    )

    op.drop_constraint(
        (
            "fk_purchase_orders_"
            "currency_id_currencies"
        ),
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_constraint(
        (
            "fk_purchase_orders_"
            "base_currency_id_currencies"
        ),
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_column(
        "purchase_orders",
        "currency_id",
    )
    op.drop_column(
        "purchase_orders",
        "base_currency_id",
    )
    op.drop_column(
        "purchase_orders",
        "exchange_rate_used",
    )

    op.drop_constraint(
        (
            "fk_purchase_phases_"
            "currency_id_currencies"
        ),
        "purchase_phases",
        type_="foreignkey",
    )
    op.drop_column(
        "purchase_phases",
        "currency_id",
    )
    op.drop_column(
        "purchase_phases",
        "exchange_rate_used",
    )
    op.drop_column(
        "purchase_phases",
        "actual_delivery_date",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_orders AS po
                JOIN companies AS company
                  ON company.id = po.company_id
                WHERE company.base_currency_id
                      IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order downgrade blocked: a company base currency is missing';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_order_lines
                GROUP BY purchase_order_id
                HAVING
                    COUNT(
                        DISTINCT currency_id
                    ) > 1
                    OR COUNT(
                        DISTINCT exchange_rate_used
                    ) > 1
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order downgrade blocked: an order contains mixed commercial terms';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_phase_allocations
                    AS allocation
                JOIN purchase_order_lines
                    AS line
                  ON line.id =
                     allocation
                     .purchase_order_line_id
                GROUP BY allocation.phase_id
                HAVING
                    COUNT(
                        DISTINCT line.currency_id
                    ) > 1
                    OR COUNT(
                        DISTINCT
                        line.exchange_rate_used
                    ) > 1
            ) THEN
                RAISE EXCEPTION
                    'Purchase-order downgrade blocked: a phase contains mixed commercial terms';
            END IF;
        END
        $$;
        """
    )

    op.add_column(
        "purchase_orders",
        sa.Column(
            "currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "base_currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "winning_quotation_response_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "purchase_phases",
        sa.Column(
            "currency_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_phases",
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_phases",
        sa.Column(
            "actual_delivery_date",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE purchase_orders AS po
        SET
            currency_id = COALESCE(
                (
                    SELECT MIN(
                        line.currency_id
                    )
                    FROM purchase_order_lines
                        AS line
                    WHERE
                        line.purchase_order_id
                        = po.id
                ),
                company.base_currency_id
            ),
            base_currency_id =
                company.base_currency_id,
            exchange_rate_used =
                COALESCE(
                    (
                        SELECT MIN(
                            line
                            .exchange_rate_used
                        )
                        FROM purchase_order_lines
                            AS line
                        WHERE
                            line
                            .purchase_order_id
                            = po.id
                    ),
                    1
                )
        FROM companies AS company
        WHERE company.id = po.company_id
        """
    )

    op.execute(
        """
        UPDATE purchase_orders AS po
        SET winning_quotation_response_id = (
            SELECT response.id
            FROM quotation_responses
                AS response
            WHERE
                response.rfq_id
                = po.source_rfq_id
                AND response.is_winner
                    IS TRUE
            ORDER BY
                response.selected_at
                    DESC NULLS LAST,
                response.updated_at DESC,
                response.id DESC
            LIMIT 1
        )
        WHERE po.source_rfq_id IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE purchase_phases AS phase
        SET
            currency_id = COALESCE(
                (
                    SELECT MIN(
                        line.currency_id
                    )
                    FROM
                        purchase_phase_allocations
                        AS allocation
                    JOIN purchase_order_lines
                        AS line
                      ON line.id =
                         allocation
                         .purchase_order_line_id
                    WHERE
                        allocation.phase_id
                        = phase.id
                ),
                po.currency_id
            ),
            exchange_rate_used = COALESCE(
                (
                    SELECT MIN(
                        line
                        .exchange_rate_used
                    )
                    FROM
                        purchase_phase_allocations
                        AS allocation
                    JOIN purchase_order_lines
                        AS line
                      ON line.id =
                         allocation
                         .purchase_order_line_id
                    WHERE
                        allocation.phase_id
                        = phase.id
                ),
                po.exchange_rate_used
            ),
            actual_delivery_date = (
                SELECT MAX(
                    receipt.receipt_date
                )::timestamp
                FROM goods_receipt_notes
                    AS receipt
                WHERE
                    receipt.purchase_phase_id
                    = phase.id
                    AND receipt.status
                        = 'posted'
            )
        FROM purchase_orders AS po
        WHERE
            po.id =
            phase.purchase_order_id
        """
    )

    op.alter_column(
        "purchase_orders",
        "currency_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "purchase_orders",
        "base_currency_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "purchase_orders",
        "exchange_rate_used",
        existing_type=sa.Numeric(
            precision=28,
            scale=10,
        ),
        nullable=False,
        server_default=sa.text("1"),
    )

    op.create_foreign_key(
        (
            "fk_purchase_orders_"
            "currency_id_currencies"
        ),
        "purchase_orders",
        "currencies",
        ["currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        (
            "fk_purchase_orders_"
            "base_currency_id_currencies"
        ),
        "purchase_orders",
        "currencies",
        ["base_currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        (
            "fk_purchase_orders_"
            "winning_quotation_response"
        ),
        "purchase_orders",
        "quotation_responses",
        ["winning_quotation_response_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        (
            "ix_purchase_orders_"
            "winning_quotation_response_id"
        ),
        "purchase_orders",
        ["winning_quotation_response_id"],
    )

    op.create_foreign_key(
        (
            "fk_purchase_phases_"
            "currency_id_currencies"
        ),
        "purchase_phases",
        "currencies",
        ["currency_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        op.f(
            "ck_purchase_orders_"
            "ck_purchase_orders_single_source"
        ),
        "purchase_orders",
        type_="check",
    )
    op.drop_constraint(
        "uq_purchase_orders_company_source_rfq",
        "purchase_orders",
        type_="unique",
    )
    op.drop_index(
        "ix_purchase_orders_source_rfq_id",
        table_name="purchase_orders",
    )
    op.drop_constraint(
        "fk_purchase_orders_source_rfq",
        "purchase_orders",
        type_="foreignkey",
    )

    op.alter_column(
        "purchase_orders",
        "source_rfq_id",
        new_column_name="rfq_id",
        existing_type=sa.Integer(),
        existing_nullable=True,
    )

    op.create_index(
        "ix_purchase_orders_rfq_id",
        "purchase_orders",
        ["rfq_id"],
    )
    op.create_foreign_key(
        "fk_purchase_orders_rfq",
        "purchase_orders",
        "rfqs",
        ["rfq_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_purchase_orders_company_rfq",
        "purchase_orders",
        [
            "company_id",
            "rfq_id",
        ],
    )
    op.create_check_constraint(
        "ck_purchase_orders_single_source",
        "purchase_orders",
        """
        NOT (
            rfq_id IS NOT NULL
            AND source_material_requisition_id
                IS NOT NULL
        )
        """,
    )
