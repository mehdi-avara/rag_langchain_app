"""make roles company aware

Revision ID: f6a1c9e2d4b7
Revises: e4c2f6a9b8d1
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1c9e2d4b7"
down_revision: Union[str, None] = "e4c2f6a9b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("roles", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("roles", sa.Column("is_system", sa.Boolean(), nullable=True))

    op.execute("UPDATE roles SET is_system = TRUE WHERE is_system IS NULL")

    op.alter_column("roles", "is_system", existing_type=sa.Boolean(), nullable=False)

    op.create_foreign_key(
        op.f("fk_roles_company_id_companies"),
        "roles",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index(op.f("ix_roles_company_id"), "roles", ["company_id"], unique=False)

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_roles_name'
        ) THEN
            ALTER TABLE roles DROP CONSTRAINT uq_roles_name;
        END IF;
    END $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'roles_name_key'
        ) THEN
            ALTER TABLE roles DROP CONSTRAINT roles_name_key;
        END IF;
    END $$;
    """)

    op.create_index(
        "uq_roles_system_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("company_id IS NULL"),
    )

    op.create_index(
        "uq_roles_company_name",
        "roles",
        ["company_id", "name"],
        unique=True,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_roles_company_name", table_name="roles")
    op.drop_index("uq_roles_system_name", table_name="roles")
    op.drop_index(op.f("ix_roles_company_id"), table_name="roles")
    op.drop_constraint(op.f("fk_roles_company_id_companies"), "roles", type_="foreignkey")
    op.drop_column("roles", "is_system")
    op.drop_column("roles", "company_id")
    op.create_unique_constraint(op.f("uq_roles_name"), "roles", ["name"])
