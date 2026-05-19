"""add profile asset to users

Revision ID: d6f0f6b7c2a1
Revises: a0f1c7559618
Create Date: 2026-05-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f0f6b7c2a1"
down_revision: Union[str, None] = "a0f1c7559618"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_asset_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_users_profile_asset_id"), "users", ["profile_asset_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_users_profile_asset_id_file_assets"),
        "users",
        "file_assets",
        ["profile_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_users_profile_asset_id_file_assets"), "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_profile_asset_id"), table_name="users")
    op.drop_column("users", "profile_asset_id")
