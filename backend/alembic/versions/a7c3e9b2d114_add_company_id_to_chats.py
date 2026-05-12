"""add company_id to chats

Revision ID: a7c3e9b2d114
Revises: 9a4d1b7e6c22
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "a7c3e9b2d114"
down_revision = "9a4d1b7e6c22"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chats", sa.Column("company_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chats_company_id_companies",
        "chats",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute("""
        UPDATE chats
        SET company_id = users.company_id
        FROM users
        WHERE chats.user_id = users.id
    """)

    op.alter_column("chats", "company_id", nullable=False)
    op.create_index("ix_chats_company_id", "chats", ["company_id"])


def downgrade():
    op.drop_index("ix_chats_company_id", table_name="chats")
    op.drop_constraint("fk_chats_company_id_companies", "chats", type_="foreignkey")
    op.drop_column("chats", "company_id")
