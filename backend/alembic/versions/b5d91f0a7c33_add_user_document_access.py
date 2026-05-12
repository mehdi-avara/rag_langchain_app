"""add user document access

Revision ID: b5d91f0a7c33
Revises: a7c3e9b2d114
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "b5d91f0a7c33"
down_revision = "a7c3e9b2d114"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_document_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_download", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_ask", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_update", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_delete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "document_id", name="uq_user_document_access_user_document"),
    )
    op.create_index("ix_user_document_access_user_id", "user_document_access", ["user_id"])
    op.create_index("ix_user_document_access_document_id", "user_document_access", ["document_id"])


def downgrade():
    op.drop_index("ix_user_document_access_document_id", table_name="user_document_access")
    op.drop_index("ix_user_document_access_user_id", table_name="user_document_access")
    op.drop_table("user_document_access")
