"""link_grn_warehouse_locations

Revision ID: f9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f9b0c1d2e3f4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM goods_receipt_notes
                LEFT JOIN warehouses
                    ON warehouses.id = goods_receipt_notes.warehouse_id
                WHERE goods_receipt_notes.warehouse_id IS NOT NULL
                  AND warehouses.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot add GRN warehouse FK: invalid warehouse_id exists';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM goods_receipt_items
                LEFT JOIN storage_locations
                    ON storage_locations.id =
                        goods_receipt_items.storage_location_id
                WHERE goods_receipt_items.storage_location_id IS NOT NULL
                  AND storage_locations.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot add GRN storage location FK: invalid storage_location_id exists';
            END IF;
        END
        $$;
        """
    )

    op.create_foreign_key(
        "fk_grn_warehouse",
        "goods_receipt_notes",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_foreign_key(
        "fk_grn_items_storage_location",
        "goods_receipt_items",
        "storage_locations",
        ["storage_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_grn_items_storage_location",
        "goods_receipt_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_grn_warehouse",
        "goods_receipt_notes",
        type_="foreignkey",
    )
