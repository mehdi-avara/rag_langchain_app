"""Close remaining Phase 1.2 backend contracts.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = (
    "b1c2d3e4f5a6"
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


SPLIT_PERMISSION = (
    "purchase_management:phases:split"
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permissions (
            name,
            resource,
            action,
            description
        )
        VALUES (
            '{SPLIT_PERMISSION}',
            'purchase_management.phases',
            'split',
            'Split unreceived delivery quantities'
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
          AND permission.name = '{SPLIT_PERMISSION}'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    pass
