"""add company_id to system_tags

Revision ID: 9a4d1b7e6c22
Revises: 8f2a7c9d4e10
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "9a4d1b7e6c22"
down_revision = "8f2a7c9d4e10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("system_tags", sa.Column("company_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_system_tags_company_id_companies",
        "system_tags",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute("""
        UPDATE system_tags t
        SET company_id = u.company_id
        FROM users u
        WHERE u.id = t.owner_id
    """)

    op.alter_column("system_tags", "company_id", nullable=False)
    op.drop_constraint("uq_system_tags_tag_name", "system_tags", type_="unique")
    op.create_unique_constraint(
        "uq_system_tags_company_id_tag_name",
        "system_tags",
        ["company_id", "tag_name"],
    )
    op.create_index("ix_system_tags_company_id", "system_tags", ["company_id"])


def downgrade():
    op.drop_index("ix_system_tags_company_id", table_name="system_tags")
    op.drop_constraint("uq_system_tags_company_id_tag_name", "system_tags", type_="unique")
    op.create_unique_constraint("uq_system_tags_tag_name", "system_tags", ["tag_name"])
    op.drop_constraint("fk_system_tags_company_id_companies", "system_tags", type_="foreignkey")
    op.drop_column("system_tags", "company_id")
