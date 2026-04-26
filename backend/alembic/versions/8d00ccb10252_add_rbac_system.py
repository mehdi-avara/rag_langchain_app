"""add rbac system

Revision ID: 8d00ccb10252
Revises: eb1676de65fe
Create Date: 2026-04-24 15:27:54.862501

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d00ccb10252"
down_revision: Union[str, None] = "eb1676de65fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
    )

    op.create_index(op.f("ix_permissions_id"), "permissions", ["id"], unique=False)
    op.create_index(op.f("ix_permissions_name"), "permissions", ["name"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
    )

    op.create_index(op.f("ix_roles_id"), "roles", ["id"], unique=False)
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name=op.f("fk_role_permission_permission_id_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permission_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permission")),
    )

    op.create_table(
        "user_role",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_user_role_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_role_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_role")),
    )


def downgrade() -> None:
    op.drop_table("user_role")
    op.drop_table("role_permission")

    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    op.drop_index(op.f("ix_roles_id"), table_name="roles")
    op.drop_table("roles")

    op.drop_index(op.f("ix_permissions_name"), table_name="permissions")
    op.drop_index(op.f("ix_permissions_id"), table_name="permissions")
    op.drop_table("permissions")