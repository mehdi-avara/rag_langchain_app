"""add financial management

Revision ID: cf8b3d9a1a21
Revises: 8d00ccb10252
Create Date: 2026-05-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "cf8b3d9a1a21"
down_revision: Union[str, None] = "8d00ccb10252"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("card_number", sa.String(), nullable=False),
        sa.Column("bank_name", sa.String(), nullable=True),
        sa.Column("account_owner_name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_financial_cards_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_cards")),
        sa.UniqueConstraint("owner_id", "card_number", name=op.f("uq_financial_cards_owner_id")),
    )
    op.create_index("ix_financial_cards_owner_id", "financial_cards", ["owner_id"], unique=False)
    op.create_index(op.f("ix_financial_cards_title"), "financial_cards", ["title"], unique=False)
    op.create_index(op.f("ix_financial_cards_card_number"), "financial_cards", ["card_number"], unique=False)
    op.create_index(op.f("ix_financial_cards_bank_name"), "financial_cards", ["bank_name"], unique=False)

    op.create_table(
        "financial_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("credit_card_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("description_embedding", Vector(dim=1024), nullable=True),
        sa.Column("tracking_number", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("counterparty_name", sa.String(), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["credit_card_id"], ["financial_cards.id"], name=op.f("fk_financial_receipts_credit_card_id_financial_cards")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_financial_receipts_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_receipts")),
    )
    op.create_index("ix_financial_receipts_owner_id", "financial_receipts", ["owner_id"], unique=False)
    op.create_index("ix_financial_receipts_credit_card_id", "financial_receipts", ["credit_card_id"], unique=False)
    op.create_index("ix_financial_receipts_tracking_number", "financial_receipts", ["tracking_number"], unique=False)
    op.create_index("ix_financial_receipts_counterparty_name", "financial_receipts", ["counterparty_name"], unique=False)
    op.create_index("ix_financial_receipts_direction", "financial_receipts", ["direction"], unique=False)
    op.create_index("ix_financial_receipts_receipt_date", "financial_receipts", ["receipt_date"], unique=False)

    op.create_table(
        "financial_receipt_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("media_address", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["financial_receipts.id"], name=op.f("fk_financial_receipt_files_receipt_id_financial_receipts"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_financial_receipt_files_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_receipt_files")),
    )
    op.create_index("ix_financial_receipt_files_receipt_id", "financial_receipt_files", ["receipt_id"], unique=False)
    op.create_index("ix_financial_receipt_files_user_id", "financial_receipt_files", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_financial_receipt_files_user_id", table_name="financial_receipt_files")
    op.drop_index("ix_financial_receipt_files_receipt_id", table_name="financial_receipt_files")
    op.drop_table("financial_receipt_files")

    op.drop_index("ix_financial_receipts_receipt_date", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_direction", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_counterparty_name", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_tracking_number", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_credit_card_id", table_name="financial_receipts")
    op.drop_index("ix_financial_receipts_owner_id", table_name="financial_receipts")
    op.drop_table("financial_receipts")

    op.drop_index(op.f("ix_financial_cards_bank_name"), table_name="financial_cards")
    op.drop_index(op.f("ix_financial_cards_card_number"), table_name="financial_cards")
    op.drop_index(op.f("ix_financial_cards_title"), table_name="financial_cards")
    op.drop_index("ix_financial_cards_owner_id", table_name="financial_cards")
    op.drop_table("financial_cards")
