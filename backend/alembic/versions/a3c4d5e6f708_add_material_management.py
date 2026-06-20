"""add_material_management

Revision ID: a3c4d5e6f708
Revises: f2a3b4c5d6e7
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

revision: str = "a3c4d5e6f708"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "item_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_item_categories_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_item_categories_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["item_categories.id"],
            name="fk_item_categories_parent_id_item_categories",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_item_categories"),
        sa.UniqueConstraint("company_id", "code", name="uq_item_categories_company_code"),
    )
    op.create_index("ix_item_categories_company_id", "item_categories", ["company_id"], unique=False)
    op.create_index("ix_item_categories_code", "item_categories", ["code"], unique=False)
    op.create_index("ix_item_categories_parent_id", "item_categories", ["parent_id"], unique=False)
    op.create_index("ix_item_categories_name", "item_categories", ["name"], unique=False)

    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("unit_type", sa.String(length=30), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_units_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_units_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_units"),
        sa.UniqueConstraint("company_id", "code", name="uq_units_company_code"),
    )
    op.create_index("ix_units_company_id", "units", ["company_id"], unique=False)
    op.create_index("ix_units_code", "units", ["code"], unique=False)
    op.create_index("ix_units_unit_type", "units", ["unit_type"], unique=False)

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("specs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("barcode", sa.String(length=255), nullable=True),
        sa.Column("qr_code", sa.String(length=255), nullable=True),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_critical", sa.Boolean(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("description_embedding", pgvector.sqlalchemy.Vector(dim=1024), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["item_categories.id"],
            name="fk_items_category_id_item_categories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_items_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_items_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["managed_models.id"],
            name="fk_items_model_id_managed_models",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="fk_items_unit_id_units",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_items"),
        sa.UniqueConstraint("company_id", "item_code", name="uq_items_company_item_code"),
    )
    op.create_index("ix_items_company_id", "items", ["company_id"], unique=False)
    op.create_index("ix_items_item_code", "items", ["item_code"], unique=False)
    op.create_index("ix_items_name", "items", ["name"], unique=False)
    op.create_index("ix_items_category_id", "items", ["category_id"], unique=False)
    op.create_index("ix_items_unit_id", "items", ["unit_id"], unique=False)
    op.create_index("ix_items_model_id", "items", ["model_id"], unique=False)
    op.create_index("ix_items_item_type", "items", ["item_type"], unique=False)
    op.create_index("ix_items_is_active", "items", ["is_active"], unique=False)
    op.create_index("ix_items_is_critical", "items", ["is_critical"], unique=False)
    op.create_index("ix_items_barcode", "items", ["barcode"], unique=False)
    op.create_index("ix_items_qr_code", "items", ["qr_code"], unique=False)

    op.create_table(
        "item_alternatives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("alt_code", sa.String(length=100), nullable=False),
        sa.Column("alt_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_item_alternatives_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_item_alternatives_item_id_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_item_alternatives_supplier_id_suppliers",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_item_alternatives"),
        sa.UniqueConstraint("item_id", "alt_code", name="uq_item_alternatives_item_alt_code"),
    )
    op.create_index("ix_item_alternatives_item_id", "item_alternatives", ["item_id"], unique=False)
    op.create_index("ix_item_alternatives_supplier_id", "item_alternatives", ["supplier_id"], unique=False)
    op.create_index("ix_item_alternatives_alt_code", "item_alternatives", ["alt_code"], unique=False)

    op.create_table(
        "item_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["file_assets.id"],
            name="fk_item_documents_asset_id_file_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_item_documents_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name="fk_item_documents_item_id_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_item_documents"),
    )
    op.create_index("ix_item_documents_item_id", "item_documents", ["item_id"], unique=False)
    op.create_index("ix_item_documents_asset_id", "item_documents", ["asset_id"], unique=False)
    op.create_index("ix_item_documents_document_type", "item_documents", ["document_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_item_documents_document_type", table_name="item_documents")
    op.drop_index("ix_item_documents_asset_id", table_name="item_documents")
    op.drop_index("ix_item_documents_item_id", table_name="item_documents")
    op.drop_table("item_documents")

    op.drop_index("ix_item_alternatives_alt_code", table_name="item_alternatives")
    op.drop_index("ix_item_alternatives_supplier_id", table_name="item_alternatives")
    op.drop_index("ix_item_alternatives_item_id", table_name="item_alternatives")
    op.drop_table("item_alternatives")

    op.drop_index("ix_items_qr_code", table_name="items")
    op.drop_index("ix_items_barcode", table_name="items")
    op.drop_index("ix_items_is_critical", table_name="items")
    op.drop_index("ix_items_is_active", table_name="items")
    op.drop_index("ix_items_item_type", table_name="items")
    op.drop_index("ix_items_model_id", table_name="items")
    op.drop_index("ix_items_unit_id", table_name="items")
    op.drop_index("ix_items_category_id", table_name="items")
    op.drop_index("ix_items_name", table_name="items")
    op.drop_index("ix_items_item_code", table_name="items")
    op.drop_index("ix_items_company_id", table_name="items")
    op.drop_table("items")

    op.drop_index("ix_units_unit_type", table_name="units")
    op.drop_index("ix_units_code", table_name="units")
    op.drop_index("ix_units_company_id", table_name="units")
    op.drop_table("units")

    op.drop_index("ix_item_categories_name", table_name="item_categories")
    op.drop_index("ix_item_categories_parent_id", table_name="item_categories")
    op.drop_index("ix_item_categories_code", table_name="item_categories")
    op.drop_index("ix_item_categories_company_id", table_name="item_categories")
    op.drop_table("item_categories")
