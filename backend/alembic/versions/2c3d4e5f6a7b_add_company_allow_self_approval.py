"""add_company_allow_self_approval

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-06-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2c3d4e5f6a7b"
down_revision: Union[str, None] = "1b2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Company admin setting that relaxes segregation of duties so a single user
    # can approve a requisition they created. Defaults to True so all companies
    # (existing rows included) allow self-approval out of the box; a company admin
    # can turn it off to enforce two-person approval.
    op.add_column(
        "companies",
        sa.Column(
            "allow_self_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "allow_self_approval")
