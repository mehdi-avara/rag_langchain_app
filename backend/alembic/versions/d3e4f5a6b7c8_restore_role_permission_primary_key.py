"""Restore role-permission association integrity.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = (
    "c2d3e4f5a6b7"
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


CONSTRAINT_NAME = "pk_role_permission"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission AS duplicate
        USING role_permission AS keeper
        WHERE duplicate.role_id = keeper.role_id
          AND duplicate.permission_id =
              keeper.permission_id
          AND duplicate.ctid > keeper.ctid
        """
    )

    op.create_primary_key(
        CONSTRAINT_NAME,
        "role_permission",
        [
            "role_id",
            "permission_id",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "role_permission",
        type_="primary",
    )
