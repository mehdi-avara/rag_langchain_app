"""add_supplier_management

Revision ID: f2a3b4c5d6e7
Revises: e1b2c3d4f5a6
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1b2c3d4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("supplier_type", sa.String(length=30), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("tax_id", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("description_embedding", pgvector.sqlalchemy.Vector(dim=1024), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_suppliers_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_suppliers_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
        sa.UniqueConstraint("company_id", "code", name="uq_suppliers_company_code"),
    )
    op.create_index("ix_suppliers_company_id", "suppliers", ["company_id"], unique=False)
    op.create_index("ix_suppliers_code", "suppliers", ["code"], unique=False)
    op.create_index("ix_suppliers_name", "suppliers", ["name"], unique=False)
    op.create_index("ix_suppliers_status", "suppliers", ["status"], unique=False)
    op.create_index("ix_suppliers_supplier_type", "suppliers", ["supplier_type"], unique=False)
    op.create_index("ix_suppliers_country", "suppliers", ["country"], unique=False)

    op.create_table(
        "supplier_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_supplier_contacts_supplier_id_suppliers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_contacts"),
    )
    op.create_index("ix_supplier_contacts_supplier_id", "supplier_contacts", ["supplier_id"], unique=False)
    op.create_index("ix_supplier_contacts_email", "supplier_contacts", ["email"], unique=False)
    op.create_index("ix_supplier_contacts_is_primary", "supplier_contacts", ["is_primary"], unique=False)

    op.create_table(
        "supplier_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_supplier_categories_supplier_id_suppliers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_categories"),
        sa.UniqueConstraint("supplier_id", "category", name="uq_supplier_categories_supplier_category"),
    )
    op.create_index("ix_supplier_categories_supplier_id", "supplier_categories", ["supplier_id"], unique=False)
    op.create_index("ix_supplier_categories_category", "supplier_categories", ["category"], unique=False)

    op.create_table(
        "supplier_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_supplier_documents_supplier_id_suppliers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["file_assets.id"],
            name="fk_supplier_documents_asset_id_file_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_supplier_documents_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_documents"),
    )
    op.create_index("ix_supplier_documents_supplier_id", "supplier_documents", ["supplier_id"], unique=False)
    op.create_index("ix_supplier_documents_asset_id", "supplier_documents", ["asset_id"], unique=False)
    op.create_index("ix_supplier_documents_document_type", "supplier_documents", ["document_type"], unique=False)
    op.create_index("ix_supplier_documents_expires_at", "supplier_documents", ["expires_at"], unique=False)

    op.create_table(
        "supplier_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("evaluator_user_id", sa.Integer(), nullable=True),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("delivery_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("price_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("service_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_supplier_evaluations_supplier_id_suppliers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evaluator_user_id"],
            ["users.id"],
            name="fk_supplier_evaluations_evaluator_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_evaluations"),
    )
    op.create_index("ix_supplier_evaluations_supplier_id", "supplier_evaluations", ["supplier_id"], unique=False)
    op.create_index("ix_supplier_evaluations_evaluator_user_id", "supplier_evaluations", ["evaluator_user_id"], unique=False)
    op.create_index("ix_supplier_evaluations_evaluation_date", "supplier_evaluations", ["evaluation_date"], unique=False)

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM purchase_orders
                WHERE supplier_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot add supplier FK: purchase_orders.supplier_id contains legacy values. Map them to suppliers first.';
            END IF;
        END $$;
        """
    )

    op.create_foreign_key(
        "fk_purchase_orders_supplier_id_suppliers",
        "purchase_orders",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_purchase_orders_supplier_id_suppliers",
        "purchase_orders",
        type_="foreignkey",
    )

    op.drop_index("ix_supplier_evaluations_evaluation_date", table_name="supplier_evaluations")
    op.drop_index("ix_supplier_evaluations_evaluator_user_id", table_name="supplier_evaluations")
    op.drop_index("ix_supplier_evaluations_supplier_id", table_name="supplier_evaluations")
    op.drop_table("supplier_evaluations")

    op.drop_index("ix_supplier_documents_expires_at", table_name="supplier_documents")
    op.drop_index("ix_supplier_documents_document_type", table_name="supplier_documents")
    op.drop_index("ix_supplier_documents_asset_id", table_name="supplier_documents")
    op.drop_index("ix_supplier_documents_supplier_id", table_name="supplier_documents")
    op.drop_table("supplier_documents")

    op.drop_index("ix_supplier_categories_category", table_name="supplier_categories")
    op.drop_index("ix_supplier_categories_supplier_id", table_name="supplier_categories")
    op.drop_table("supplier_categories")

    op.drop_index("ix_supplier_contacts_is_primary", table_name="supplier_contacts")
    op.drop_index("ix_supplier_contacts_email", table_name="supplier_contacts")
    op.drop_index("ix_supplier_contacts_supplier_id", table_name="supplier_contacts")
    op.drop_table("supplier_contacts")

    op.drop_index("ix_suppliers_country", table_name="suppliers")
    op.drop_index("ix_suppliers_supplier_type", table_name="suppliers")
    op.drop_index("ix_suppliers_status", table_name="suppliers")
    op.drop_index("ix_suppliers_name", table_name="suppliers")
    op.drop_index("ix_suppliers_code", table_name="suppliers")
    op.drop_index("ix_suppliers_company_id", table_name="suppliers")
    op.drop_table("suppliers")
