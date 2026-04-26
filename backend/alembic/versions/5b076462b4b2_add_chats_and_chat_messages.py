"""add chats and chat_messages

Revision ID: 5b076462b4b2
Revises: a6d10c6403f5
Create Date: 2025-12-27 18:22:30.671702

"""
from typing import Sequence, Union

from alembic import op


revision: str = "5b076462b4b2"
down_revision: Union[str, None] = "a6d10c6403f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE system_tags DROP CONSTRAINT IF EXISTS uq_system_tags_tag_name")
    op.create_unique_constraint(
        op.f("uq_system_tags_tag_name"),
        "system_tags",
        ["tag_name"],
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_tags DROP CONSTRAINT IF EXISTS uq_system_tags_tag_name")