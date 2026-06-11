"""add financial multi currency

Revision ID: 8c1d2e3f4a50
Revises: 7f2b6c9d1a40
Create Date: 2026-06-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c1d2e3f4a50"
down_revision: Union[str, None] = "7f2b6c9d1a40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("base_currency", sa.String(length=12), nullable=False, server_default="IRT"))

    op.add_column("financial_receipts", sa.Column("currency", sa.String(length=12), nullable=False, server_default="IRT"))
    op.add_column("financial_receipts", sa.Column("base_currency", sa.String(length=12), nullable=False, server_default="IRT"))
    op.add_column("financial_receipts", sa.Column("exchange_rate_to_base", sa.Numeric(18, 6), nullable=False, server_default="1"))
    op.add_column("financial_receipts", sa.Column("base_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("financial_receipts", sa.Column("exchange_rate_source", sa.String(length=20), nullable=False, server_default="system"))

    op.execute("""
        UPDATE financial_receipts
        SET base_amount = amount
        WHERE base_amount IS NULL
    """)

    op.alter_column("financial_receipts", "base_amount", nullable=False)

    op.create_index("ix_financial_receipts_currency", "financial_receipts", ["currency"])
    op.create_index("ix_financial_receipts_base_currency", "financial_receipts", ["base_currency"])


def downgrade() -> None:
    op.drop_index("ix_financial_receipts_base_currency", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_currency", table_name="financial_receipts")

    op.drop_column("financial_receipts", "exchange_rate_source")
    op.drop_column("financial_receipts", "base_amount")
    op.drop_column("financial_receipts", "exchange_rate_to_base")
    op.drop_column("financial_receipts", "base_currency")
    op.drop_column("financial_receipts", "currency")

    op.drop_column("companies", "base_currency")
