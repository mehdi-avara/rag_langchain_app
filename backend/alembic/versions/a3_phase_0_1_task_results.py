"""phase_0.1 — task_results table for async Celery task tracking

Revision ID: a3_phase_0_1_task_results
Revises: a2_phase_0_2_purchase
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a3_phase_0_1_task_results"
down_revision: Union[str, None] = "a2_phase_0_2_purchase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_results",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("result_json", JSONB, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_task_results_celery_task_id", "task_results", ["celery_task_id"])
    op.create_index("ix_task_results_status", "task_results", ["status"])
    op.create_index("ix_task_results_created_by_user_id", "task_results", ["created_by_user_id"])
    op.create_index("ix_task_results_task_type", "task_results", ["task_type"])


def downgrade() -> None:
    op.drop_index("ix_task_results_task_type", table_name="task_results")
    op.drop_index("ix_task_results_created_by_user_id", table_name="task_results")
    op.drop_index("ix_task_results_status", table_name="task_results")
    op.drop_index("ix_task_results_celery_task_id", table_name="task_results")
    op.drop_table("task_results")
