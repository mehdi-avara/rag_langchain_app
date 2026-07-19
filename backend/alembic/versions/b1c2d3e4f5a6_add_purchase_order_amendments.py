"""Add purchase-order commercial amendments.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = (
    "a0b1c2d3e4f5"
)
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


SUBMIT_PERMISSION = (
    "purchase_management:orders:submit"
)
AMEND_PERMISSION = (
    "purchase_management:orders:amend"
)


def upgrade() -> None:
    op.create_table(
        "purchase_order_amendments",
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
            "purchase_order_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "amendment_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "before_snapshot",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            nullable=False,
        ),
        sa.Column(
            "proposed_snapshot",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            nullable=True,
        ),
        sa.Column(
            "submission_note",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "decision_note",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "submitted_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amendment_number >= 1",
            name=(
                "purchase_order_amendment_"
                "number_positive"
            ),
        ),
        sa.CheckConstraint(
            """
            status IN (
                'draft',
                'pending',
                'approved',
                'rejected'
            )
            """,
            name=(
                "purchase_order_amendment_"
                "status_valid"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=(
                "fk_purchase_order_amendments_"
                "company_id"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=(
                "fk_purchase_order_amendments_"
                "purchase_order_id"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=(
                "fk_purchase_order_amendments_"
                "created_by_user_id"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name=(
                "fk_purchase_order_amendments_"
                "submitted_by_user_id"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=(
                "fk_purchase_order_amendments_"
                "decided_by_user_id"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_purchase_order_amendments",
        ),
        sa.UniqueConstraint(
            "company_id",
            "purchase_order_id",
            "amendment_number",
            name=(
                "uq_purchase_order_amendments_"
                "company_order_number"
            ),
        ),
    )

    op.create_index(
        "ix_purchase_order_amendments_"
        "company_created",
        "purchase_order_amendments",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_purchase_order_amendments_"
        "order_number",
        "purchase_order_amendments",
        [
            "purchase_order_id",
            "amendment_number",
        ],
    )
    op.create_index(
        "ix_purchase_order_amendments_"
        "created_by_user_id",
        "purchase_order_amendments",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_purchase_order_amendments_"
        "submitted_by_user_id",
        "purchase_order_amendments",
        ["submitted_by_user_id"],
    )
    op.create_index(
        "ix_purchase_order_amendments_"
        "decided_by_user_id",
        "purchase_order_amendments",
        ["decided_by_user_id"],
    )
    op.create_index(
        "uq_purchase_order_amendments_"
        "active_order",
        "purchase_order_amendments",
        ["purchase_order_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('draft', 'pending')"
        ),
    )

    op.execute(
        f"""
        INSERT INTO permissions (
            name,
            resource,
            action,
            description
        )
        VALUES
        (
            '{SUBMIT_PERMISSION}',
            'purchase_management.orders',
            'submit',
            'Submit purchase orders and amendments for approval'
        ),
        (
            '{AMEND_PERMISSION}',
            'purchase_management.orders',
            'amend',
            'Open commercial amendments for approved purchase orders'
        )
        ON CONFLICT (name)
        DO UPDATE SET
            resource = EXCLUDED.resource,
            action = EXCLUDED.action,
            description = EXCLUDED.description
        """
    )

    op.execute(
        f"""
        INSERT INTO role_permission (
            role_id,
            permission_id
        )
        SELECT
            role.id,
            permission.id
        FROM roles AS role
        CROSS JOIN permissions AS permission
        WHERE role.name = 'admin'
          AND role.company_id IS NULL
          AND permission.name IN (
              '{SUBMIT_PERMISSION}',
              '{AMEND_PERMISSION}'
          )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permission
        WHERE permission_id IN (
            SELECT id
            FROM permissions
            WHERE name IN (
                '{SUBMIT_PERMISSION}',
                '{AMEND_PERMISSION}'
            )
        )
        """
    )

    op.execute(
        f"""
        DELETE FROM permissions
        WHERE name IN (
            '{SUBMIT_PERMISSION}',
            '{AMEND_PERMISSION}'
        )
        """
    )

    op.drop_index(
        "uq_purchase_order_amendments_"
        "active_order",
        table_name="purchase_order_amendments",
    )
    op.drop_index(
        "ix_purchase_order_amendments_"
        "decided_by_user_id",
        table_name="purchase_order_amendments",
    )
    op.drop_index(
        "ix_purchase_order_amendments_"
        "submitted_by_user_id",
        table_name="purchase_order_amendments",
    )
    op.drop_index(
        "ix_purchase_order_amendments_"
        "created_by_user_id",
        table_name="purchase_order_amendments",
    )
    op.drop_index(
        "ix_purchase_order_amendments_"
        "order_number",
        table_name="purchase_order_amendments",
    )
    op.drop_index(
        "ix_purchase_order_amendments_"
        "company_created",
        table_name="purchase_order_amendments",
    )
    op.drop_table(
        "purchase_order_amendments"
    )
