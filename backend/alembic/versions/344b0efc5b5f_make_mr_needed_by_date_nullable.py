"""Make material requisition needed date optional."""

from alembic import op
import sqlalchemy as sa


revision = "344b0efc5b5f"
down_revision = "5f6a7b8c9d0a"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "material_requisitions",
        "needed_by_date",
        existing_type=sa.Date(),
        nullable=True,
    )


def downgrade():
    op.execute(
        """
        UPDATE material_requisitions
        SET needed_by_date = CAST(created_at AS DATE)
        WHERE needed_by_date IS NULL
        """
    )
    op.alter_column(
        "material_requisitions",
        "needed_by_date",
        existing_type=sa.Date(),
        nullable=False,
    )
