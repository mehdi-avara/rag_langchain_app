"""link_purchase_orders_to_rfq

Revision ID: 0a1b2c3d4e5f
Revises: f9b0c1d2e3f4
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, None] = "f9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("rfq_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "winning_quotation_response_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_purchase_orders_rfq_id",
        "purchase_orders",
        ["rfq_id"],
    )
    op.create_index(
        "ix_purchase_orders_winning_quotation_response_id",
        "purchase_orders",
        ["winning_quotation_response_id"],
    )
    op.create_foreign_key(
        "fk_purchase_orders_rfq",
        "purchase_orders",
        "rfqs",
        ["rfq_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_purchase_orders_winning_quotation_response",
        "purchase_orders",
        "quotation_responses",
        ["winning_quotation_response_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_purchase_orders_company_rfq",
        "purchase_orders",
        ["company_id", "rfq_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_purchase_orders_company_rfq",
        "purchase_orders",
        type_="unique",
    )
    op.drop_constraint(
        "fk_purchase_orders_winning_quotation_response",
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_purchase_orders_rfq",
        "purchase_orders",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_purchase_orders_winning_quotation_response_id",
        table_name="purchase_orders",
    )
    op.drop_index(
        "ix_purchase_orders_rfq_id",
        table_name="purchase_orders",
    )
    op.drop_column(
        "purchase_orders",
        "winning_quotation_response_id",
    )
    op.drop_column("purchase_orders", "rfq_id")
