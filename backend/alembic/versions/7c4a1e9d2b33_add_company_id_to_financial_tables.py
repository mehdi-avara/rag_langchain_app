"""add company id to financial tables

Revision ID: 7c4a1e9d2b33
Revises: 6b9c2f3d8a11
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c4a1e9d2b33"
down_revision: Union[str, None] = "6b9c2f3d8a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_cards", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("financial_receipts", sa.Column("company_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE financial_cards fc
        SET company_id = u.company_id
        FROM users u
        WHERE fc.owner_id = u.id
        AND fc.company_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE financial_receipts fr
        SET company_id = u.company_id
        FROM users u
        WHERE fr.owner_id = u.id
        AND fr.company_id IS NULL
        """
    )

    op.alter_column("financial_cards", "company_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("financial_receipts", "company_id", existing_type=sa.Integer(), nullable=False)

    op.create_foreign_key(
        op.f("fk_financial_cards_company_id_companies"),
        "financial_cards",
        "companies",
        ["company_id"],
        ["id"],
    )

    op.create_foreign_key(
        op.f("fk_financial_receipts_company_id_companies"),
        "financial_receipts",
        "companies",
        ["company_id"],
        ["id"],
    )

    op.create_index(op.f("ix_financial_cards_company_id"), "financial_cards", ["company_id"], unique=False)
    op.create_index(op.f("ix_financial_receipts_company_id"), "financial_receipts", ["company_id"], unique=False)

    op.drop_constraint("uq_financial_cards_owner_id", "financial_cards", type_="unique")

    op.create_unique_constraint(
        op.f("uq_financial_cards_company_id"),
        "financial_cards",
        ["company_id", "card_number"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_financial_cards_company_id"), "financial_cards", type_="unique")
    op.create_unique_constraint(
        "uq_financial_cards_owner_id",
        "financial_cards",
        ["owner_id", "card_number"],
    )

    op.drop_index(op.f("ix_financial_receipts_company_id"), table_name="financial_receipts")
    op.drop_index(op.f("ix_financial_cards_company_id"), table_name="financial_cards")

    op.drop_constraint(op.f("fk_financial_receipts_company_id_companies"), "financial_receipts", type_="foreignkey")
    op.drop_constraint(op.f("fk_financial_cards_company_id_companies"), "financial_cards", type_="foreignkey")

    op.drop_column("financial_receipts", "company_id")
    op.drop_column("financial_cards", "company_id")
