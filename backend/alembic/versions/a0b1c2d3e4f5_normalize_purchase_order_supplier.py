"""Normalize purchase-order supplier ownership.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = (
    "f9a0b1c2d3e4"
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


FK_NAME = (
    "fk_purchase_orders_"
    "supplier_id_suppliers"
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_orders
                WHERE supplier_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Purchase supplier normalization blocked: a purchase order has no supplier_id';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_orders AS po
                LEFT JOIN suppliers AS supplier
                  ON supplier.id = po.supplier_id
                WHERE supplier.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Purchase supplier normalization blocked: an invalid supplier reference exists';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_orders AS po
                JOIN suppliers AS supplier
                  ON supplier.id = po.supplier_id
                WHERE supplier.company_id
                      <> po.company_id
            ) THEN
                RAISE EXCEPTION
                    'Purchase supplier normalization blocked: a supplier belongs to another company';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_orders AS po
                JOIN suppliers AS supplier
                  ON supplier.id = po.supplier_id
                WHERE
                    NULLIF(
                        BTRIM(po.supplier_name),
                        ''
                    )
                    IS DISTINCT FROM
                    NULLIF(
                        BTRIM(supplier.name),
                        ''
                    )
            ) THEN
                RAISE EXCEPTION
                    'Purchase supplier normalization blocked: stored supplier names do not match supplier records';
            END IF;
        END
        $$;
        """
    )

    op.drop_index(
        "ix_purchase_orders_supplier_name",
        table_name="purchase_orders",
    )

    op.drop_constraint(
        FK_NAME,
        "purchase_orders",
        type_="foreignkey",
    )

    op.alter_column(
        "purchase_orders",
        "supplier_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        FK_NAME,
        "purchase_orders",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_column(
        "purchase_orders",
        "supplier_name",
    )


def downgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column(
            "supplier_name",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE purchase_orders AS po
        SET supplier_name = supplier.name
        FROM suppliers AS supplier
        WHERE supplier.id = po.supplier_id
        """
    )

    op.create_index(
        "ix_purchase_orders_supplier_name",
        "purchase_orders",
        ["supplier_name"],
    )

    op.drop_constraint(
        FK_NAME,
        "purchase_orders",
        type_="foreignkey",
    )

    op.alter_column(
        "purchase_orders",
        "supplier_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        FK_NAME,
        "purchase_orders",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )
