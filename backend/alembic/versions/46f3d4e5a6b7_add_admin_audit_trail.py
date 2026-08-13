"""Add admin audit trail.

Revision ID: 46f3d4e5a6b7
Revises: 35e2c3d4f5a6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "46f3d4e5a6b7"
down_revision: str | None = "35e2c3d4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "details_json",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            nullable=False,
            server_default=sa.text(
                "'{}'::jsonb"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_admin_audit_company_created",
        "admin_audit_logs",
        [
            "company_id",
            "created_at",
        ],
    )

    op.create_index(
        "ix_admin_audit_actor_created",
        "admin_audit_logs",
        [
            "actor_user_id",
            "created_at",
        ],
    )

    op.create_index(
        "ix_admin_audit_action",
        "admin_audit_logs",
        ["action"],
    )

    op.create_index(
        "ix_admin_audit_target",
        "admin_audit_logs",
        [
            "target_type",
            "target_id",
        ],
    )


def downgrade() -> None:
    op.drop_table(
        "admin_audit_logs"
    )
