"""Add authentication session foundation.

Revision ID: 24d1b2c3e4f5
Revises: 13c0a1b2d3e4
Create Date: 2026-08-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "24d1b2c3e4f5"
down_revision: Union[
    str,
    None,
] = "13c0a1b2d3e4"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_check_constraint(
        "ck_users_auth_token_version_nonnegative",
        "users",
        "auth_token_version >= 0",
    )

    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "refresh_jti_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "last_rotated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "revoked_reason",
            sa.String(length=64),
            nullable=True,
        ),
        sa.CheckConstraint(
            "token_version >= 0",
            name=(
                "ck_auth_sessions_"
                "token_version_nonnegative"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_auth_sessions_company_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_auth_sessions",
        ),
        sa.UniqueConstraint(
            "refresh_jti_hash",
            name=(
                "uq_auth_sessions_"
                "refresh_jti_hash"
            ),
        ),
    )

    op.create_index(
        "ix_auth_sessions_user_id",
        "auth_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_company_id",
        "auth_sessions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_expires_at",
        "auth_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_revoked_at",
        "auth_sessions",
        ["revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_sessions_revoked_at",
        table_name="auth_sessions",
    )
    op.drop_index(
        "ix_auth_sessions_expires_at",
        table_name="auth_sessions",
    )
    op.drop_index(
        "ix_auth_sessions_company_id",
        table_name="auth_sessions",
    )
    op.drop_index(
        "ix_auth_sessions_user_id",
        table_name="auth_sessions",
    )

    op.drop_table(
        "auth_sessions"
    )

    op.drop_constraint(
        "ck_users_auth_token_version_nonnegative",
        "users",
        type_="check",
    )

    op.drop_column(
        "users",
        "auth_token_version",
    )
