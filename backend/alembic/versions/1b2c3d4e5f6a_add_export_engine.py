"""add_export_engine

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "1b2c3d4e5f6a"
down_revision: Union[str, None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "task_result_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("file_asset_id", sa.Integer(), nullable=True),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("entity", sa.String(length=80), nullable=False),
        sa.Column("export_format", sa.String(length=10), nullable=False),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "columns_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_result_id"],
            ["task_results.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id"],
            ["file_assets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_export_audit_company_created",
        "export_audit_logs",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_export_audit_user_created",
        "export_audit_logs",
        ["requested_by_user_id", "created_at"],
    )
    op.create_index(
        "ix_export_audit_module_entity",
        "export_audit_logs",
        ["module", "entity"],
    )
    op.create_index(
        "ix_export_audit_status",
        "export_audit_logs",
        ["status"],
    )
    op.create_index(
        "ix_export_audit_task_result_id",
        "export_audit_logs",
        ["task_result_id"],
    )
    op.create_index(
        "ix_export_audit_file_asset_id",
        "export_audit_logs",
        ["file_asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_export_audit_file_asset_id",
        table_name="export_audit_logs",
    )
    op.drop_index(
        "ix_export_audit_task_result_id",
        table_name="export_audit_logs",
    )
    op.drop_index(
        "ix_export_audit_status",
        table_name="export_audit_logs",
    )
    op.drop_index(
        "ix_export_audit_module_entity",
        table_name="export_audit_logs",
    )
    op.drop_index(
        "ix_export_audit_user_created",
        table_name="export_audit_logs",
    )
    op.drop_index(
        "ix_export_audit_company_created",
        table_name="export_audit_logs",
    )
    op.drop_table("export_audit_logs")
