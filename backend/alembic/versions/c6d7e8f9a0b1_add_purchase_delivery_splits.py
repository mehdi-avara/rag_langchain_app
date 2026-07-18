"""Add idempotent purchase delivery splits.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-07-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = (
    "b5c6d7e8f9a0"
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


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT
                    purchase_order_id,
                    phase_number
                FROM purchase_phases
                GROUP BY
                    purchase_order_id,
                    phase_number
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Delivery split migration blocked: duplicate phase numbers exist within a purchase order';
            END IF;
        END
        $$;
        """
    )

    op.create_unique_constraint(
        "uq_purchase_phases_order_phase_number",
        "purchase_phases",
        [
            "purchase_order_id",
            "phase_number",
        ],
    )

    op.create_table(
        "purchase_phase_split_events",
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
            "target_phase_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "details_json",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            server_default=sa.text(
                "'{}'::jsonb"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=(
                "fk_purchase_phase_split_events_company"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=(
                "fk_purchase_phase_split_events_order"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_phase_id"],
            ["purchase_phases.id"],
            name=(
                "fk_purchase_phase_split_events_target_phase"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=(
                "fk_purchase_phase_split_events_actor"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=(
                "pk_purchase_phase_split_events"
            ),
        ),
        sa.UniqueConstraint(
            "company_id",
            "purchase_order_id",
            "idempotency_key",
            name=(
                "uq_purchase_phase_split_events_scope_key"
            ),
        ),
    )

    op.create_index(
        "ix_purchase_phase_split_events_company_created",
        "purchase_phase_split_events",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_purchase_phase_split_events_order_created",
        "purchase_phase_split_events",
        [
            "purchase_order_id",
            "created_at",
        ],
    )
    op.create_index(
        "ix_purchase_phase_split_events_target_phase_id",
        "purchase_phase_split_events",
        ["target_phase_id"],
    )
    op.create_index(
        "ix_purchase_phase_split_events_actor_user_id",
        "purchase_phase_split_events",
        ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_phase_split_events_actor_user_id",
        table_name=(
            "purchase_phase_split_events"
        ),
    )
    op.drop_index(
        "ix_purchase_phase_split_events_target_phase_id",
        table_name=(
            "purchase_phase_split_events"
        ),
    )
    op.drop_index(
        "ix_purchase_phase_split_events_order_created",
        table_name=(
            "purchase_phase_split_events"
        ),
    )
    op.drop_index(
        "ix_purchase_phase_split_events_company_created",
        table_name=(
            "purchase_phase_split_events"
        ),
    )
    op.drop_table(
        "purchase_phase_split_events"
    )

    op.drop_constraint(
        "uq_purchase_phases_order_phase_number",
        "purchase_phases",
        type_="unique",
    )
