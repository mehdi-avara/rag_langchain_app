"""add user security fields

Revision ID: e4c2f6a9b8d1
Revises: d6f0f6b7c2a1
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4c2f6a9b8d1"
down_revision: Union[str, None] = "d6f0f6b7c2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE users SET is_active = TRUE WHERE is_active IS NULL")

    op.alter_column("users", "is_active", existing_type=sa.Boolean(), nullable=False)
    op.create_index(op.f("ix_users_is_active"), "users", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_is_active"), table_name="users")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_active")
