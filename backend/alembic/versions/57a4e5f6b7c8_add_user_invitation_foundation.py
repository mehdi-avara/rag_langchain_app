"""Add secure tenant user invitation foundation.

Revision ID: 57a4e5f6b7c8
Revises: 46f3d4e5a6b7
"""

from alembic import op
import sqlalchemy as sa


revision: str = "57a4e5f6b7c8"
down_revision: str | None = "46f3d4e5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_invitations",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "first_name",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "last_name",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "role_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),
        sa.CheckConstraint(
            "role_count >= 1",
            name="role_count_positive",
        ),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL "
            "AND revoked_at IS NOT NULL)",
            name="terminal_state_exclusive",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=(
                "fk_user_invitations_"
                "company_id_companies"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=(
                "fk_user_invitations_"
                "invited_by_user_id_users"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_user_invitations",
        ),
        sa.UniqueConstraint(
            "token_hash",
            name=(
                "uq_user_invitations_"
                "token_hash"
            ),
        ),
    )

    op.create_index(
        "ix_user_invitations_company_created",
        "user_invitations",
        [
            "company_id",
            "created_at",
        ],
    )

    op.create_index(
        "ix_user_invitations_company_email",
        "user_invitations",
        [
            "company_id",
            "email",
        ],
    )

    op.create_index(
        "ix_user_invitations_expires_at",
        "user_invitations",
        [
            "expires_at",
        ],
    )

    op.create_index(
        "uq_user_invitations_open_company_email",
        "user_invitations",
        [
            "company_id",
            "email",
        ],
        unique=True,
        postgresql_where=sa.text(
            "accepted_at IS NULL "
            "AND revoked_at IS NULL"
        ),
    )

    op.create_table(
        "user_invitation_role",
        sa.Column(
            "invitation_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["user_invitations.id"],
            name=(
                "fk_user_invitation_role_"
                "invitation_id_user_invitations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=(
                "fk_user_invitation_role_"
                "role_id_roles"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "invitation_id",
            "role_id",
            name="pk_user_invitation_role",
        ),
    )

    op.create_index(
        "ix_user_invitation_role_role_id",
        "user_invitation_role",
        [
            "role_id",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_invitation_role_role_id",
        table_name="user_invitation_role",
    )

    op.drop_table(
        "user_invitation_role"
    )

    op.drop_index(
        "uq_user_invitations_open_company_email",
        table_name="user_invitations",
    )

    op.drop_index(
        "ix_user_invitations_expires_at",
        table_name="user_invitations",
    )

    op.drop_index(
        "ix_user_invitations_company_email",
        table_name="user_invitations",
    )

    op.drop_index(
        "ix_user_invitations_company_created",
        table_name="user_invitations",
    )

    op.drop_table(
        "user_invitations"
    )
