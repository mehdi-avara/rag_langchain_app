"""add company_id to managed_models

Revision ID: 8f2a7c9d4e10
Revises: 7c4a1e9d2b33
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "8f2a7c9d4e10"
down_revision = "7c4a1e9d2b33"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("managed_models", sa.Column("company_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_managed_models_company_id_companies",
        "managed_models",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute("""
        UPDATE managed_models m
        SET company_id = u.company_id
        FROM users u
        WHERE u.id = m.owner_id
    """)

    op.alter_column("managed_models", "company_id", nullable=False)
    op.drop_constraint("uq_managed_models_manufacturer", "managed_models", type_="unique")
    op.create_unique_constraint(
        "uq_managed_models_company_id_manufacturer_model",
        "managed_models",
        ["company_id", "manufacturer", "model"],
    )
    op.create_index("ix_managed_models_company_id", "managed_models", ["company_id"])


def downgrade():
    op.drop_index("ix_managed_models_company_id", table_name="managed_models")
    op.drop_constraint("uq_managed_models_company_id_manufacturer_model", "managed_models", type_="unique")
    op.create_unique_constraint(
        "uq_managed_models_manufacturer",
        "managed_models",
        ["manufacturer", "model"],
    )
    op.drop_constraint("fk_managed_models_company_id_companies", "managed_models", type_="foreignkey")
    op.drop_column("managed_models", "company_id")
