"""make financial customer contact fields required

Revision ID: 7f2b6c9d1a40
Revises: 0c7a9f2d6b31
Create Date: 2026-06-10 15:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f2b6c9d1a40"
down_revision: Union[str, None] = "0c7a9f2d6b31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE financial_customers
        SET access_method = 'phone'
        WHERE access_method IS NULL OR btrim(access_method) = ''
    """)

    op.execute("""
        UPDATE financial_customers
        SET phone_number1 = COALESCE(NULLIF(btrim(phone_number1), ''), NULLIF(btrim(phone_number2), ''), 'unknown')
        WHERE phone_number1 IS NULL OR btrim(phone_number1) = ''
    """)

    op.alter_column(
        "financial_customers",
        "phone_number1",
        existing_type=sa.String(),
        nullable=False,
    )

    op.alter_column(
        "financial_customers",
        "access_method",
        existing_type=sa.String(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "financial_customers",
        "access_method",
        existing_type=sa.String(),
        nullable=True,
    )

    op.alter_column(
        "financial_customers",
        "phone_number1",
        existing_type=sa.String(),
        nullable=True,
    )
