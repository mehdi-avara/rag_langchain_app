"""add assistant debug events

Revision ID: 5f6a7b8c9d0a
Revises: 4e5f6a7b8c9
Create Date: 2026-07-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "5f6a7b8c9d0a"
down_revision: Union[str, None] = "4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive enum expansion keeps all existing chat role values and APIs valid.
    op.execute("ALTER TYPE chat_role_enum ADD VALUE IF NOT EXISTS 'system'")
    op.execute("ALTER TYPE chat_role_enum ADD VALUE IF NOT EXISTS 'tool'")
    op.add_column("assistant_agent_runs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("assistant_agent_runs", sa.Column("input_message_id", sa.Integer(), nullable=True))
    op.add_column("assistant_agent_runs", sa.Column("output_message_id", sa.Integer(), nullable=True))
    op.add_column("assistant_agent_runs", sa.Column("current_stage", sa.String(length=64), nullable=True))
    op.add_column(
        "assistant_agent_runs",
        sa.Column("last_event_sequence", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "assistant_agent_runs",
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.add_column("assistant_agent_runs", sa.Column("completed_at", sa.DateTime(), nullable=True))

    # Safe identity backfill: the original column is a required FK and has
    # exactly the same initiating-user semantics for historical rows.
    op.execute("UPDATE assistant_agent_runs SET user_id = created_by_user_id WHERE user_id IS NULL")

    op.create_foreign_key(
        "fk_assistant_agent_runs_user_id_users",
        "assistant_agent_runs", "users", ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_assistant_agent_runs_input_message_id_chat_messages",
        "assistant_agent_runs", "chat_messages", ["input_message_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_assistant_agent_runs_output_message_id_chat_messages",
        "assistant_agent_runs", "chat_messages", ["output_message_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_assistant_agent_runs_input_message_id", "assistant_agent_runs", ["input_message_id"]
    )
    op.create_index(
        "ix_assistant_agent_runs_output_message_id", "assistant_agent_runs", ["output_message_id"]
    )

    op.create_table(
        "assistant_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="info", nullable=False),
        sa.Column("selected_module", sa.String(length=96), nullable=True),
        sa.Column("selected_task", sa.String(length=128), nullable=True),
        sa.Column("route_from", sa.String(length=128), nullable=True),
        sa.Column("route_to", sa.String(length=128), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["assistant_agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id", "sequence", name="uq_assistant_events_agent_run_id_sequence"
        ),
    )
    op.create_index(
        "ix_assistant_events_company_chat_created",
        "assistant_events", ["company_id", "chat_id", "created_at"],
    )
    op.create_index(
        "ix_assistant_events_run_sequence", "assistant_events", ["agent_run_id", "sequence"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_events_run_sequence", table_name="assistant_events")
    op.drop_index("ix_assistant_events_company_chat_created", table_name="assistant_events")
    op.drop_table("assistant_events")

    op.drop_index("ix_assistant_agent_runs_output_message_id", table_name="assistant_agent_runs")
    op.drop_constraint(
        "uq_assistant_agent_runs_input_message_id", "assistant_agent_runs", type_="unique"
    )
    op.drop_constraint(
        "fk_assistant_agent_runs_output_message_id_chat_messages", "assistant_agent_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_assistant_agent_runs_input_message_id_chat_messages", "assistant_agent_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_assistant_agent_runs_user_id_users", "assistant_agent_runs", type_="foreignkey"
    )
    op.drop_column("assistant_agent_runs", "completed_at")
    op.drop_column("assistant_agent_runs", "started_at")
    op.drop_column("assistant_agent_runs", "last_event_sequence")
    op.drop_column("assistant_agent_runs", "current_stage")
    op.drop_column("assistant_agent_runs", "output_message_id")
    op.drop_column("assistant_agent_runs", "input_message_id")
    op.drop_column("assistant_agent_runs", "user_id")
    # PostgreSQL cannot safely remove enum values in-place. Leaving the two
    # additive values is backward compatible for a schema downgrade.
