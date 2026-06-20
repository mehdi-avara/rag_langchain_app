"""add_purchase_phase_item_id

Revision ID: b4c5d6e7f809
Revises: a3c4d5e6f708
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4c5d6e7f809"
down_revision: Union[str, None] = "a3c4d5e6f708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_phase_items",
        sa.Column("item_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_phase_items_item_id_items",
        "purchase_phase_items",
        "items",
        ["item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_purchase_phase_items_item_id",
        "purchase_phase_items",
        ["item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_phase_items_item_id", table_name="purchase_phase_items")
    op.drop_constraint(
        "fk_purchase_phase_items_item_id_items",
        "purchase_phase_items",
        type_="foreignkey",
    )
    op.drop_column("purchase_phase_items", "item_id")
