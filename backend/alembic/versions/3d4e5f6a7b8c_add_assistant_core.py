"""add_assistant_core

Adds the generic AI-assistant tables (``assistant_agent_runs``,
``assistant_drafts``), the ``supports_vision`` flag on ``chat_ai_models`` and the
``draft_id`` reference on ``chat_messages`` (PROMPT_financial_assistant §4, §7, §8.1).

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-06-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "3d4e5f6a7b8c"
down_revision: Union[str, None] = "2c3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("intake_mode", sa.String(length=16), nullable=True),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assistant_agent_runs_chat_id", "assistant_agent_runs", ["chat_id"])
    op.create_index("ix_assistant_agent_runs_company_id", "assistant_agent_runs", ["company_id"])
    op.create_index("ix_assistant_agent_runs_status", "assistant_agent_runs", ["status"])

    op.create_table(
        "assistant_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("target_module", sa.String(length=64), server_default="financial_management", nullable=False),
        sa.Column("target_action", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "commit_target",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "validation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("committed_entity_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["assistant_agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assistant_drafts_chat_id", "assistant_drafts", ["chat_id"])
    op.create_index("ix_assistant_drafts_company_id", "assistant_drafts", ["company_id"])
    op.create_index("ix_assistant_drafts_created_by_user_id", "assistant_drafts", ["created_by_user_id"])
    op.create_index("ix_assistant_drafts_status", "assistant_drafts", ["status"])

    op.add_column(
        "chat_ai_models",
        sa.Column("supports_vision", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.add_column(
        "chat_messages",
        sa.Column("draft_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_messages_draft_id_assistant_drafts",
        "chat_messages",
        "assistant_drafts",
        ["draft_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_chat_messages_draft_id_assistant_drafts",
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_column("chat_messages", "draft_id")
    op.drop_column("chat_ai_models", "supports_vision")

    op.drop_index("ix_assistant_drafts_status", table_name="assistant_drafts")
    op.drop_index("ix_assistant_drafts_created_by_user_id", table_name="assistant_drafts")
    op.drop_index("ix_assistant_drafts_company_id", table_name="assistant_drafts")
    op.drop_index("ix_assistant_drafts_chat_id", table_name="assistant_drafts")
    op.drop_table("assistant_drafts")

    op.drop_index("ix_assistant_agent_runs_status", table_name="assistant_agent_runs")
    op.drop_index("ix_assistant_agent_runs_company_id", table_name="assistant_agent_runs")
    op.drop_index("ix_assistant_agent_runs_chat_id", table_name="assistant_agent_runs")
    op.drop_table("assistant_agent_runs")
