"""Add direct material requisition purchase orders.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = (
    "c6d7e8f9a0b1"
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
                SELECT
                    company_id,
                    source_material_requisition_id
                FROM purchase_orders
                WHERE
                    source_material_requisition_id
                    IS NOT NULL
                GROUP BY
                    company_id,
                    source_material_requisition_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Direct MR migration blocked: duplicate purchase orders exist for a material requisition';
            END IF;
        END
        $$;
        """
    )

    op.create_unique_constraint(
        "uq_purchase_orders_company_source_mr",
        "purchase_orders",
        [
            "company_id",
            "source_material_requisition_id",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_purchase_orders_company_source_mr",
        "purchase_orders",
        type_="unique",
    )
