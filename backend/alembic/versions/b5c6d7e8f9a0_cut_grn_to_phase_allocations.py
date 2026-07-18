"""Cut goods receipts over to purchase phase allocations.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items
                WHERE purchase_phase_allocation_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'GRN cutover blocked: receipt items without allocation mappings exist';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items AS receipt_item
                JOIN goods_receipt_notes AS receipt_note
                  ON receipt_note.id
                     = receipt_item.goods_receipt_note_id
                JOIN purchase_phase_allocations AS allocation
                  ON allocation.id
                     = receipt_item.purchase_phase_allocation_id
                JOIN purchase_order_lines AS order_line
                  ON order_line.id
                     = allocation.purchase_order_line_id
                WHERE allocation.phase_id
                      <> receipt_note.purchase_phase_id
                   OR order_line.purchase_order_id
                      <> receipt_note.purchase_order_id
            ) THEN
                RAISE EXCEPTION
                    'GRN cutover blocked: receipt allocation scope mismatch exists';
            END IF;
        END
        $$;
        """
    )

    op.alter_column(
        "goods_receipt_items",
        "purchase_phase_item_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.alter_column(
        "goods_receipt_items",
        "purchase_phase_allocation_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            validate_goods_receipt_allocation_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            allocation_phase_id INTEGER;
            allocation_purchase_order_id INTEGER;
            receipt_phase_id INTEGER;
            receipt_purchase_order_id INTEGER;
        BEGIN
            SELECT
                allocation.phase_id,
                order_line.purchase_order_id
            INTO
                allocation_phase_id,
                allocation_purchase_order_id
            FROM purchase_phase_allocations AS allocation
            JOIN purchase_order_lines AS order_line
              ON order_line.id
                 = allocation.purchase_order_line_id
            WHERE allocation.id
                  = NEW.purchase_phase_allocation_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Purchase phase allocation % was not found',
                    NEW.purchase_phase_allocation_id;
            END IF;

            SELECT
                receipt_note.purchase_phase_id,
                receipt_note.purchase_order_id
            INTO
                receipt_phase_id,
                receipt_purchase_order_id
            FROM goods_receipt_notes AS receipt_note
            WHERE receipt_note.id
                  = NEW.goods_receipt_note_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Goods receipt note % was not found',
                    NEW.goods_receipt_note_id;
            END IF;

            IF allocation_phase_id <> receipt_phase_id
               OR allocation_purchase_order_id
                  <> receipt_purchase_order_id
            THEN
                RAISE EXCEPTION
                    'Goods receipt allocation must belong to the receipt phase and purchase order';
            END IF;

            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER
            trg_goods_receipt_items_allocation_scope
        BEFORE INSERT OR UPDATE OF
            goods_receipt_note_id,
            purchase_phase_allocation_id
        ON goods_receipt_items
        FOR EACH ROW
        EXECUTE FUNCTION
            validate_goods_receipt_allocation_scope();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items
                WHERE purchase_phase_item_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'GRN downgrade blocked: normalized-only receipt items exist';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_goods_receipt_items_allocation_scope
        ON goods_receipt_items;

        DROP FUNCTION IF EXISTS
            validate_goods_receipt_allocation_scope();
        """
    )

    op.alter_column(
        "goods_receipt_items",
        "purchase_phase_allocation_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.alter_column(
        "goods_receipt_items",
        "purchase_phase_item_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
