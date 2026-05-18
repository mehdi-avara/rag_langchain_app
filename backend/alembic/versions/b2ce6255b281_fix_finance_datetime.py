"""fix finance datetime

Revision ID: b2ce6255b281
Revises: 08f9c75fc755
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2ce6255b281"
down_revision: Union[str, None] = "08f9c75fc755"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "financial_receipts",
        "receipt_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="receipt_date::timestamp",
    )


def downgrade() -> None:
    op.alter_column(
        "financial_receipts",
        "receipt_date",
        existing_type=sa.DateTime(),
        type_=sa.Date(),
        existing_nullable=False,
        postgresql_using="receipt_date::date",
    )
