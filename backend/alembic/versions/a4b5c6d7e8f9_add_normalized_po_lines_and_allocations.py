"""Add normalized purchase-order lines and delivery allocations.

Revision ID: a4b5c6d7e8f9
Revises: 9d0e1f2a3b4c
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "a4b5c6d7e8f9"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column(
            "source_material_requisition_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_purchase_orders_source_material_requisition_id",
        "purchase_orders",
        ["source_material_requisition_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_purchase_orders_source_material_requisition_id",
        "purchase_orders",
        "material_requisitions",
        ["source_material_requisition_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_purchase_orders_single_source",
        "purchase_orders",
        """
        NOT (
            rfq_id IS NOT NULL
            AND source_material_requisition_id IS NOT NULL
        )
        """,
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column(
            "ordered_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("line_description", sa.Text(), nullable=True),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column(
            "unit_price_base",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column(
            "exchange_rate_used",
            sa.Numeric(precision=28, scale=10),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "line_number >= 1",
            name="ck_purchase_order_lines_line_number_positive",
        ),
        sa.CheckConstraint(
            "ordered_quantity > 0",
            name="ck_purchase_order_lines_quantity_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="ck_purchase_order_lines_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "unit_price_base >= 0",
            name="ck_purchase_order_lines_unit_price_base_nonnegative",
        ),
        sa.CheckConstraint(
            "exchange_rate_used > 0",
            name="ck_purchase_order_lines_exchange_rate_positive",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name="fk_purchase_order_lines_purchase_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_purchase_order_lines_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="fk_purchase_order_lines_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
            name="fk_purchase_order_lines_currency",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_purchase_order_lines",
        ),
        sa.UniqueConstraint(
            "purchase_order_id",
            "line_number",
            name="uq_purchase_order_lines_order_line_number",
        ),
    )
    op.create_index(
        "ix_purchase_order_lines_purchase_order_id",
        "purchase_order_lines",
        ["purchase_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_lines_item_id",
        "purchase_order_lines",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_lines_unit_id",
        "purchase_order_lines",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_lines_currency_id",
        "purchase_order_lines",
        ["currency_id"],
        unique=False,
    )

    op.create_table(
        "purchase_phase_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), nullable=False),
        sa.Column(
            "allocated_quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "allocated_quantity > 0",
            name="ck_purchase_phase_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["purchase_phases.id"],
            name="fk_purchase_phase_allocations_phase",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id"],
            ["purchase_order_lines.id"],
            name="fk_purchase_phase_allocations_order_line",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_purchase_phase_allocations",
        ),
        sa.UniqueConstraint(
            "phase_id",
            "purchase_order_line_id",
            name="uq_purchase_phase_allocations_phase_line",
        ),
    )
    op.create_index(
        "ix_purchase_phase_allocations_phase_id",
        "purchase_phase_allocations",
        ["phase_id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_phase_allocations_order_line_id",
        "purchase_phase_allocations",
        ["purchase_order_line_id"],
        unique=False,
    )

    op.add_column(
        "goods_receipt_items",
        sa.Column(
            "purchase_phase_allocation_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_grn_items_phase_allocation_id",
        "goods_receipt_items",
        ["purchase_phase_allocation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_grn_items_phase_allocation",
        "goods_receipt_items",
        "purchase_phase_allocations",
        ["purchase_phase_allocation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_phase_items
                WHERE item_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill blocked: a legacy purchase phase item has no item_id';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_phase_items AS phase_item
                JOIN purchase_phases AS phase
                  ON phase.id = phase_item.phase_id
                JOIN purchase_orders AS purchase_order
                  ON purchase_order.id = phase.purchase_order_id
                LEFT JOIN items AS item
                  ON item.id = phase_item.item_id
                WHERE item.id IS NULL
                   OR item.company_id <> purchase_order.company_id
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill blocked: a legacy item is missing or belongs to another company';
            END IF;

            IF EXISTS (
                WITH unit_matches AS (
                    SELECT
                        phase_item.id,
                        COUNT(unit_row.id) AS match_count
                    FROM purchase_phase_items AS phase_item
                    JOIN purchase_phases AS phase
                      ON phase.id = phase_item.phase_id
                    JOIN purchase_orders AS purchase_order
                      ON purchase_order.id = phase.purchase_order_id
                    LEFT JOIN units AS unit_row
                      ON unit_row.company_id = purchase_order.company_id
                     AND LOWER(BTRIM(unit_row.code))
                         = LOWER(BTRIM(phase_item.unit))
                    GROUP BY phase_item.id
                )
                SELECT 1
                FROM unit_matches
                WHERE match_count <> 1
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill blocked: a legacy unit has zero or multiple company unit matches';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                WITH posted_totals AS (
                    SELECT
                        receipt_item.purchase_phase_item_id,
                        SUM(receipt_item.accepted_quantity) AS accepted_quantity
                    FROM goods_receipt_items AS receipt_item
                    JOIN goods_receipt_notes AS receipt_note
                      ON receipt_note.id = receipt_item.goods_receipt_note_id
                    WHERE receipt_note.status = 'posted'
                    GROUP BY receipt_item.purchase_phase_item_id
                )
                SELECT 1
                FROM purchase_phase_items AS phase_item
                LEFT JOIN posted_totals
                  ON posted_totals.purchase_phase_item_id = phase_item.id
                WHERE phase_item.received_quantity
                      <> COALESCE(posted_totals.accepted_quantity, 0)
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill blocked: legacy received quantities do not match posted GRN accepted quantities';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TEMPORARY TABLE phase_1_2_legacy_rows
        ON COMMIT DROP
        AS
        WITH mapped_rows AS (
            SELECT
                phase_item.id AS legacy_phase_item_id,
                phase_item.phase_id,
                phase.purchase_order_id,
                phase_item.item_id,
                unit_row.id AS unit_id,
                phase_item.quantity,
                phase_item.unit_price,
                phase_item.currency_id,
                phase_item.unit_price_base,
                phase_item.exchange_rate_used,
                phase_item.notes,
                phase_item.created_at,
                phase_item.updated_at
            FROM purchase_phase_items AS phase_item
            JOIN purchase_phases AS phase
              ON phase.id = phase_item.phase_id
            JOIN purchase_orders AS purchase_order
              ON purchase_order.id = phase.purchase_order_id
            JOIN units AS unit_row
              ON unit_row.company_id = purchase_order.company_id
             AND LOWER(BTRIM(unit_row.code))
                 = LOWER(BTRIM(phase_item.unit))
        )
        SELECT
            mapped_rows.*,
            ROW_NUMBER() OVER (
                PARTITION BY
                    phase_id,
                    item_id,
                    unit_id,
                    unit_price,
                    currency_id,
                    unit_price_base,
                    exchange_rate_used
                ORDER BY legacy_phase_item_id
            ) AS occurrence_number
        FROM mapped_rows
        """
    )

    op.execute(
        """
        CREATE TEMPORARY TABLE phase_1_2_line_groups
        ON COMMIT DROP
        AS
        WITH grouped_rows AS (
            SELECT
                purchase_order_id,
                item_id,
                unit_id,
                unit_price,
                currency_id,
                unit_price_base,
                exchange_rate_used,
                occurrence_number,
                SUM(quantity) AS ordered_quantity,
                MIN(legacy_phase_item_id) AS first_legacy_phase_item_id,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at,
                STRING_AGG(
                    DISTINCT NULLIF(BTRIM(notes), ''),
                    E'\\n---\\n'
                ) FILTER (
                    WHERE NULLIF(BTRIM(notes), '') IS NOT NULL
                ) AS combined_notes
            FROM phase_1_2_legacy_rows
            GROUP BY
                purchase_order_id,
                item_id,
                unit_id,
                unit_price,
                currency_id,
                unit_price_base,
                exchange_rate_used,
                occurrence_number
        )
        SELECT
            grouped_rows.*,
            ROW_NUMBER() OVER (
                PARTITION BY purchase_order_id
                ORDER BY first_legacy_phase_item_id
            )::INTEGER AS line_number
        FROM grouped_rows
        """
    )

    op.execute(
        """
        INSERT INTO purchase_order_lines (
            purchase_order_id,
            line_number,
            item_id,
            ordered_quantity,
            unit_id,
            line_description,
            unit_price,
            currency_id,
            unit_price_base,
            exchange_rate_used,
            notes,
            created_at,
            updated_at
        )
        SELECT
            purchase_order_id,
            line_number,
            item_id,
            ordered_quantity,
            unit_id,
            NULL,
            unit_price,
            currency_id,
            unit_price_base,
            exchange_rate_used,
            combined_notes,
            created_at,
            updated_at
        FROM phase_1_2_line_groups
        ORDER BY purchase_order_id, line_number
        """
    )

    op.execute(
        """
        ALTER TABLE phase_1_2_line_groups
        ADD COLUMN purchase_order_line_id INTEGER
        """
    )

    op.execute(
        """
        UPDATE phase_1_2_line_groups AS line_group
        SET purchase_order_line_id = purchase_order_line.id
        FROM purchase_order_lines AS purchase_order_line
        WHERE purchase_order_line.purchase_order_id
              = line_group.purchase_order_id
          AND purchase_order_line.line_number
              = line_group.line_number
        """
    )

    op.execute(
        """
        CREATE TEMPORARY TABLE phase_1_2_legacy_item_line_map
        ON COMMIT DROP
        AS
        SELECT
            legacy_row.legacy_phase_item_id,
            legacy_row.phase_id,
            line_group.purchase_order_line_id
        FROM phase_1_2_legacy_rows AS legacy_row
        JOIN phase_1_2_line_groups AS line_group
          ON line_group.purchase_order_id
             = legacy_row.purchase_order_id
         AND line_group.item_id
             = legacy_row.item_id
         AND line_group.unit_id
             = legacy_row.unit_id
         AND line_group.unit_price
             = legacy_row.unit_price
         AND line_group.currency_id
             = legacy_row.currency_id
         AND line_group.unit_price_base
             = legacy_row.unit_price_base
         AND line_group.exchange_rate_used
             = legacy_row.exchange_rate_used
         AND line_group.occurrence_number
             = legacy_row.occurrence_number
        """
    )

    op.execute(
        """
        INSERT INTO purchase_phase_allocations (
            phase_id,
            purchase_order_line_id,
            allocated_quantity,
            created_at,
            updated_at
        )
        SELECT
            legacy_row.phase_id,
            item_line_map.purchase_order_line_id,
            SUM(legacy_row.quantity),
            MIN(legacy_row.created_at),
            MAX(legacy_row.updated_at)
        FROM phase_1_2_legacy_rows AS legacy_row
        JOIN phase_1_2_legacy_item_line_map AS item_line_map
          ON item_line_map.legacy_phase_item_id
             = legacy_row.legacy_phase_item_id
        GROUP BY
            legacy_row.phase_id,
            item_line_map.purchase_order_line_id
        ORDER BY
            legacy_row.phase_id,
            item_line_map.purchase_order_line_id
        """
    )

    op.execute(
        """
        UPDATE goods_receipt_items AS receipt_item
        SET purchase_phase_allocation_id = allocation.id
        FROM phase_1_2_legacy_item_line_map AS item_line_map
        JOIN purchase_phase_allocations AS allocation
          ON allocation.phase_id = item_line_map.phase_id
         AND allocation.purchase_order_line_id
             = item_line_map.purchase_order_line_id
        WHERE receipt_item.purchase_phase_item_id
              = item_line_map.legacy_phase_item_id
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_phase_items AS phase_item
                LEFT JOIN phase_1_2_legacy_item_line_map AS item_line_map
                  ON item_line_map.legacy_phase_item_id = phase_item.id
                WHERE item_line_map.legacy_phase_item_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill failed: a legacy phase item has no normalized PO-line mapping';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items
                WHERE purchase_phase_item_id IS NOT NULL
                  AND purchase_phase_allocation_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill failed: a GRN item has no normalized allocation mapping';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM purchase_order_lines AS purchase_order_line
                LEFT JOIN (
                    SELECT
                        purchase_order_line_id,
                        SUM(allocated_quantity) AS allocated_quantity
                    FROM purchase_phase_allocations
                    GROUP BY purchase_order_line_id
                ) AS allocation_total
                  ON allocation_total.purchase_order_line_id
                     = purchase_order_line.id
                WHERE purchase_order_line.ordered_quantity
                      <> COALESCE(allocation_total.allocated_quantity, 0)
            ) THEN
                RAISE EXCEPTION
                    'Phase 1.2 backfill failed: PO-line allocation totals do not equal ordered quantities';
            END IF;
        END
        $$;
        """
    )

    op.create_unique_constraint(
        "uq_grn_items_phase_allocation",
        "goods_receipt_items",
        [
            "goods_receipt_note_id",
            "purchase_phase_allocation_id",
        ],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            enforce_purchase_phase_allocation_same_order()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            phase_purchase_order_id INTEGER;
            line_purchase_order_id INTEGER;
        BEGIN
            SELECT purchase_order_id
            INTO phase_purchase_order_id
            FROM purchase_phases
            WHERE id = NEW.phase_id;

            SELECT purchase_order_id
            INTO line_purchase_order_id
            FROM purchase_order_lines
            WHERE id = NEW.purchase_order_line_id;

            IF phase_purchase_order_id IS NULL
               OR line_purchase_order_id IS NULL
               OR phase_purchase_order_id <> line_purchase_order_id
            THEN
                RAISE EXCEPTION
                    'Purchase phase and purchase-order line must belong to the same purchase order';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER
            trg_purchase_phase_allocations_same_order
        BEFORE INSERT OR UPDATE OF
            phase_id,
            purchase_order_line_id
        ON purchase_phase_allocations
        FOR EACH ROW
        EXECUTE FUNCTION
            enforce_purchase_phase_allocation_same_order()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_purchase_phase_allocations_same_order
        ON purchase_phase_allocations
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            enforce_purchase_phase_allocation_same_order()
        """
    )

    op.drop_constraint(
        "uq_grn_items_phase_allocation",
        "goods_receipt_items",
        type_="unique",
    )
    op.drop_constraint(
        "fk_grn_items_phase_allocation",
        "goods_receipt_items",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_grn_items_phase_allocation_id",
        table_name="goods_receipt_items",
    )
    op.drop_column(
        "goods_receipt_items",
        "purchase_phase_allocation_id",
    )

    op.drop_table("purchase_phase_allocations")
    op.drop_table("purchase_order_lines")

    op.drop_constraint(
        "ck_purchase_orders_single_source",
        "purchase_orders",
        type_="check",
    )
    op.drop_constraint(
        "fk_purchase_orders_source_material_requisition_id",
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_purchase_orders_source_material_requisition_id",
        table_name="purchase_orders",
    )
    op.drop_column(
        "purchase_orders",
        "source_material_requisition_id",
    )
