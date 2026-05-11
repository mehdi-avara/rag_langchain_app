"""add companies and user company id

Revision ID: 6b9c2f3d8a11
Revises: 13b271d29b71
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b9c2f3d8a11"
down_revision: Union[str, None] = "13b271d29b71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
    )

    op.create_index(op.f("ix_companies_slug"), "companies", ["slug"], unique=True)

    op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=True))

    op.create_index(
        op.f("ix_users_company_id"),
        "users",
        ["company_id"],
        unique=False,
    )

    op.create_foreign_key(
        op.f("fk_users_company_id_companies"),
        "users",
        "companies",
        ["company_id"],
        ["id"],
    )

    op.execute(
        """
        INSERT INTO companies (name, slug, is_active, created_at)
        VALUES ('Default Company', 'default-company', true, now())
        ON CONFLICT (slug) DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE users
        SET company_id = (
            SELECT id
            FROM companies
            WHERE slug = 'default-company'
            LIMIT 1
        )
        WHERE company_id IS NULL
        """
    )

    op.alter_column(
        "users",
        "company_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "company_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.drop_constraint(
        op.f("fk_users_company_id_companies"),
        "users",
        type_="foreignkey",
    )

    op.drop_index(op.f("ix_users_company_id"), table_name="users")

    op.drop_column("users", "company_id")

    op.drop_index(op.f("ix_companies_slug"), table_name="companies")

    op.drop_table("companies")

