"""merge_heads

Revision ID: f12b914c7d4e
Revises: 8c1d2e3f4a50, a1b2c3d4e5f6, a3_phase_0_1_task_results
Create Date: 2026-06-16 11:25:35.719229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f12b914c7d4e'
down_revision: Union[str, None] = ('8c1d2e3f4a50', 'a1b2c3d4e5f6', 'a3_phase_0_1_task_results')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
