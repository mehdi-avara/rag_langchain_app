"""Restore role-permission association integrity.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


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
EXPECTED_COLUMNS = [
    "role_id",
    "permission_id",
]


def _rename_primary_key(
    current_name: str,
) -> None:
    bind = op.get_bind()
    preparer = (
        bind.dialect.identifier_preparer
    )

    table_name = preparer.quote(
        "role_permission"
    )
    old_name = preparer.quote(
        current_name
    )
    new_name = preparer.quote(
        CONSTRAINT_NAME
    )

    op.execute(
        sa.text(
            f"ALTER TABLE {table_name} "
            f"RENAME CONSTRAINT "
            f"{old_name} TO {new_name}"
        )
    )


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

    bind = op.get_bind()
    primary_key = (
        sa.inspect(bind)
        .get_pk_constraint(
            "role_permission"
        )
    )

    current_name = primary_key.get(
        "name"
    )
    current_columns = (
        primary_key.get(
            "constrained_columns"
        )
        or []
    )

    if current_columns == EXPECTED_COLUMNS:
        if (
            current_name
            and current_name
            != CONSTRAINT_NAME
        ):
            _rename_primary_key(
                current_name
            )

        return

    if current_name:
        op.drop_constraint(
            current_name,
            "role_permission",
            type_="primary",
        )

    op.create_primary_key(
        CONSTRAINT_NAME,
        "role_permission",
        EXPECTED_COLUMNS,
    )


def downgrade() -> None:
    pass
