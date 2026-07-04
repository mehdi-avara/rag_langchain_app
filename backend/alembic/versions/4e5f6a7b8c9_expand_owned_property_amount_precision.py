"""expand_owned_property_amount_precision

Revision ID: 4e5f6a7b8c9
Revises: 3d4e5f6a7b8c
Create Date: 2026-07-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "4e5f6a7b8c9"
down_revision: Union[str, None] = "3d4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "owned_properties",
        "purchase_cost",
        existing_type=sa.Numeric(precision=14, scale=2),
        type_=sa.Numeric(precision=24, scale=2),
        existing_nullable=True,
    )
    op.alter_column(
        "owned_properties",
        "current_estimated_value",
        existing_type=sa.Numeric(precision=14, scale=2),
        type_=sa.Numeric(precision=24, scale=2),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "owned_properties",
        "current_estimated_value",
        existing_type=sa.Numeric(precision=24, scale=2),
        type_=sa.Numeric(precision=14, scale=2),
        existing_nullable=True,
    )
    op.alter_column(
        "owned_properties",
        "purchase_cost",
        existing_type=sa.Numeric(precision=24, scale=2),
        type_=sa.Numeric(precision=14, scale=2),
        existing_nullable=True,
    )
