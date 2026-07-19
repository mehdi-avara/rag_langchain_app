"""Remove legacy purchase phase items.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = (
    "d7e8f9a0b1c2"
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
                FROM purchase_phase_items AS legacy
                WHERE (
                    SELECT COUNT(*)
                    FROM purchase_phase_allocations
                        AS allocation
                    JOIN purchase_order_lines
                        AS line
                      ON line.id =
                         allocation
                         .purchase_order_line_id
                    JOIN purchase_phases AS phase
                      ON phase.id =
                         allocation.phase_id
                    JOIN purchase_orders AS po
                      ON po.id =
                         phase.purchase_order_id
                    JOIN units AS unit_row
                      ON unit_row.id =
                         line.unit_id
                    WHERE
                        allocation.phase_id
                        = legacy.phase_id
                        AND line.item_id
                            IS NOT DISTINCT FROM
                            legacy.item_id
                        AND allocation
                            .allocated_quantity
                            IS NOT DISTINCT FROM
                            legacy.quantity
                        AND UPPER(
                            BTRIM(unit_row.code)
                        ) IS NOT DISTINCT FROM
                            UPPER(
                                BTRIM(legacy.unit)
                            )
                        AND line.unit_price
                            IS NOT DISTINCT FROM
                            legacy.unit_price
                        AND line.currency_id
                            IS NOT DISTINCT FROM
                            legacy.currency_id
                        AND line.unit_price_base
                            IS NOT DISTINCT FROM
                            legacy.unit_price_base
                        AND po.base_currency_id
                            IS NOT DISTINCT FROM
                            legacy.base_currency_id
                        AND line.exchange_rate_used
                            IS NOT DISTINCT FROM
                            legacy.exchange_rate_used
                ) <> 1
            ) THEN
                RAISE EXCEPTION
                    'Legacy phase-item removal blocked: every legacy item must map to exactly one normalized allocation';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items AS gri
                WHERE
                    gri.purchase_phase_item_id
                    IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM purchase_phase_items
                            AS legacy
                        JOIN purchase_phase_allocations
                            AS allocation
                          ON allocation.id =
                             gri
                             .purchase_phase_allocation_id
                        JOIN purchase_order_lines
                            AS line
                          ON line.id =
                             allocation
                             .purchase_order_line_id
                        JOIN purchase_phases
                            AS phase
                          ON phase.id =
                             allocation.phase_id
                        JOIN purchase_orders AS po
                          ON po.id =
                             phase.purchase_order_id
                        JOIN units AS unit_row
                          ON unit_row.id =
                             line.unit_id
                        WHERE
                            legacy.id =
                            gri.purchase_phase_item_id
                            AND legacy.phase_id =
                                allocation.phase_id
                            AND legacy.item_id
                                IS NOT DISTINCT FROM
                                line.item_id
                            AND legacy.quantity
                                IS NOT DISTINCT FROM
                                allocation
                                .allocated_quantity
                            AND UPPER(
                                BTRIM(legacy.unit)
                            ) IS NOT DISTINCT FROM
                                UPPER(
                                    BTRIM(
                                        unit_row.code
                                    )
                                )
                            AND legacy.unit_price
                                IS NOT DISTINCT FROM
                                line.unit_price
                            AND legacy.currency_id
                                IS NOT DISTINCT FROM
                                line.currency_id
                            AND legacy
                                .unit_price_base
                                IS NOT DISTINCT FROM
                                line.unit_price_base
                            AND legacy
                                .base_currency_id
                                IS NOT DISTINCT FROM
                                po.base_currency_id
                            AND legacy
                                .exchange_rate_used
                                IS NOT DISTINCT FROM
                                line
                                .exchange_rate_used
                    )
            ) THEN
                RAISE EXCEPTION
                    'Legacy phase-item removal blocked: a GRN legacy link does not match its normalized allocation';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        UPDATE goods_receipt_items
        SET purchase_phase_item_id = NULL
        WHERE purchase_phase_item_id
              IS NOT NULL
        """
    )

    op.drop_constraint(
        "uq_grn_items_phase_item",
        "goods_receipt_items",
        type_="unique",
    )
    op.drop_index(
        "ix_grn_items_phase_item_id",
        table_name="goods_receipt_items",
    )
    op.drop_constraint(
        "fk_grn_items_phase_item",
        "goods_receipt_items",
        type_="foreignkey",
    )
    op.drop_column(
        "goods_receipt_items",
        "purchase_phase_item_id",
    )

    op.drop_table(
        "purchase_phase_items"
    )


def downgrade() -> None:
    op.create_table(
        "purchase_phase_items",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "phase_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "item_name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "item_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "quantity",
            sa.Numeric(
                precision=18,
                scale=4,
            ),
            nullable=False,
        ),
        sa.Column(
            "received_quantity",
            sa.Numeric(
                precision=18,
                scale=4,
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unit",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'pcs'"),
        ),
        sa.Column(
            "unit_price",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "currency_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "unit_price_base",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "base_currency_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "line_total",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "line_total_base",
            sa.Numeric(
                precision=28,
                scale=10,
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["purchase_phases.id"],
            name=(
                "fk_purchase_phase_items_"
                "phase_id_purchase_phases"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name=(
                "fk_purchase_phase_items_"
                "item_id_items"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name=(
                "fk_purchase_phase_items_"
                "currency_id_currencies"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_currency_id"],
            ["currencies.id"],
            name=(
                "fk_purchase_phase_items_"
                "base_currency_id_currencies"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_purchase_phase_items",
        ),
    )

    op.create_index(
        "ix_purchase_phase_items_phase_id",
        "purchase_phase_items",
        ["phase_id"],
    )
    op.create_index(
        "ix_purchase_phase_items_item_id",
        "purchase_phase_items",
        ["item_id"],
    )
    op.create_index(
        "ix_purchase_phase_items_item_code",
        "purchase_phase_items",
        ["item_code"],
    )

    op.add_column(
        "goods_receipt_items",
        sa.Column(
            "purchase_phase_item_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_grn_items_phase_item",
        "goods_receipt_items",
        "purchase_phase_items",
        ["purchase_phase_item_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_grn_items_phase_item",
        "goods_receipt_items",
        [
            "goods_receipt_note_id",
            "purchase_phase_item_id",
        ],
    )
    op.create_index(
        "ix_grn_items_phase_item_id",
        "goods_receipt_items",
        ["purchase_phase_item_id"],
    )

    op.execute(
        """
        INSERT INTO purchase_phase_items (
            id,
            phase_id,
            item_name,
            item_code,
            quantity,
            received_quantity,
            unit,
            unit_price,
            currency_id,
            unit_price_base,
            base_currency_id,
            exchange_rate_used,
            line_total,
            line_total_base,
            notes,
            created_at,
            updated_at,
            item_id
        )
        SELECT
            allocation.id,
            allocation.phase_id,
            material.name,
            material.item_code,
            allocation.allocated_quantity,
            COALESCE(
                SUM(
                    CASE
                        WHEN receipt.status = 'posted'
                        THEN receipt_item
                             .accepted_quantity
                        ELSE 0
                    END
                ),
                0
            ),
            unit_row.code,
            line.unit_price,
            line.currency_id,
            line.unit_price_base,
            po.base_currency_id,
            line.exchange_rate_used,
            allocation.allocated_quantity
                * line.unit_price,
            allocation.allocated_quantity
                * line.unit_price_base,
            line.notes,
            allocation.created_at,
            allocation.updated_at,
            line.item_id
        FROM purchase_phase_allocations
            AS allocation
        JOIN purchase_order_lines AS line
          ON line.id =
             allocation.purchase_order_line_id
        JOIN purchase_phases AS phase
          ON phase.id = allocation.phase_id
        JOIN purchase_orders AS po
          ON po.id = phase.purchase_order_id
        JOIN items AS material
          ON material.id = line.item_id
        JOIN units AS unit_row
          ON unit_row.id = line.unit_id
        LEFT JOIN goods_receipt_items
            AS receipt_item
          ON receipt_item
             .purchase_phase_allocation_id
             = allocation.id
        LEFT JOIN goods_receipt_notes
            AS receipt
          ON receipt.id =
             receipt_item
             .goods_receipt_note_id
        GROUP BY
            allocation.id,
            allocation.phase_id,
            material.name,
            material.item_code,
            allocation.allocated_quantity,
            unit_row.code,
            line.unit_price,
            line.currency_id,
            line.unit_price_base,
            po.base_currency_id,
            line.exchange_rate_used,
            line.notes,
            allocation.created_at,
            allocation.updated_at,
            line.item_id
        """
    )

    op.execute(
        """
        UPDATE goods_receipt_items
        SET purchase_phase_item_id =
            purchase_phase_allocation_id
        """
    )

    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence(
                'purchase_phase_items',
                'id'
            ),
            COALESCE(
                (
                    SELECT MAX(id)
                    FROM purchase_phase_items
                ),
                1
            ),
            EXISTS (
                SELECT 1
                FROM purchase_phase_items
            )
        )
        """
    )
