"""add property management and financial customers

Revision ID: c2d8f8e4b1a1
Revises: 7c4a1e9d2b33
Create Date: 2026-05-16 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d8f8e4b1a1"
down_revision: Union[str, None] = "7c4a1e9d2b33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone_number1", sa.String(), nullable=True),
        sa.Column("phone_number2", sa.String(), nullable=True),
        sa.Column("access_method", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_financial_customers_company_id_companies")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_financial_customers_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_customers")),
    )
    op.create_index(op.f("ix_financial_customers_company_id"), "financial_customers", ["company_id"], unique=False)
    op.create_index(op.f("ix_financial_customers_owner_id"), "financial_customers", ["owner_id"], unique=False)
    op.create_index(op.f("ix_financial_customers_name"), "financial_customers", ["name"], unique=False)
    op.create_index(op.f("ix_financial_customers_phone_number1"), "financial_customers", ["phone_number1"], unique=False)
    op.create_index(op.f("ix_financial_customers_phone_number2"), "financial_customers", ["phone_number2"], unique=False)
    op.create_index(op.f("ix_financial_customers_access_method"), "financial_customers", ["access_method"], unique=False)
    op.create_index(op.f("ix_financial_customers_email"), "financial_customers", ["email"], unique=False)

    op.add_column("financial_receipts", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_financial_receipts_customer_id_financial_customers"),
        "financial_receipts",
        "financial_customers",
        ["customer_id"],
        ["id"],
    )
    op.create_index(op.f("ix_financial_receipts_customer_id"), "financial_receipts", ["customer_id"], unique=False)

    op.create_table(
        "warehouse_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("unit_current_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_warehouse_items_company_id_companies")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_warehouse_items_owner_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["managed_models.id"], name=op.f("fk_warehouse_items_model_id_managed_models"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouse_items")),
        sa.UniqueConstraint("company_id", "model_id", "color", name=op.f("uq_warehouse_items_company_id")),
    )
    op.create_index(op.f("ix_warehouse_items_company_id"), "warehouse_items", ["company_id"], unique=False)
    op.create_index(op.f("ix_warehouse_items_owner_id"), "warehouse_items", ["owner_id"], unique=False)
    op.create_index(op.f("ix_warehouse_items_model_id"), "warehouse_items", ["model_id"], unique=False)
    op.create_index(op.f("ix_warehouse_items_color"), "warehouse_items", ["color"], unique=False)

    op.create_table(
        "owned_properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("purchase_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("current_estimated_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_owned_properties_company_id_companies")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_owned_properties_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owned_properties")),
    )
    op.create_index(op.f("ix_owned_properties_company_id"), "owned_properties", ["company_id"], unique=False)
    op.create_index(op.f("ix_owned_properties_owner_id"), "owned_properties", ["owner_id"], unique=False)
    op.create_index(op.f("ix_owned_properties_category"), "owned_properties", ["category"], unique=False)
    op.create_index(op.f("ix_owned_properties_title"), "owned_properties", ["title"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_owned_properties_title"), table_name="owned_properties")
    op.drop_index(op.f("ix_owned_properties_category"), table_name="owned_properties")
    op.drop_index(op.f("ix_owned_properties_owner_id"), table_name="owned_properties")
    op.drop_index(op.f("ix_owned_properties_company_id"), table_name="owned_properties")
    op.drop_table("owned_properties")

    op.drop_index(op.f("ix_warehouse_items_color"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_model_id"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_owner_id"), table_name="warehouse_items")
    op.drop_index(op.f("ix_warehouse_items_company_id"), table_name="warehouse_items")
    op.drop_table("warehouse_items")

    op.drop_index(op.f("ix_financial_receipts_customer_id"), table_name="financial_receipts")
    op.drop_constraint(op.f("fk_financial_receipts_customer_id_financial_customers"), "financial_receipts", type_="foreignkey")
    op.drop_column("financial_receipts", "customer_id")

    op.drop_index(op.f("ix_financial_customers_email"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_access_method"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_phone_number2"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_phone_number1"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_name"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_owner_id"), table_name="financial_customers")
    op.drop_index(op.f("ix_financial_customers_company_id"), table_name="financial_customers")
    op.drop_table("financial_customers")
