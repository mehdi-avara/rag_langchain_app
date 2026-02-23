"""cascade delete chunks when document deleted

Revision ID: eb1676de65fe
Revises: 9ea390ba32a0
Create Date: 2026-02-23 08:38:23.900776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb1676de65fe'
down_revision: Union[str, None] = '9ea390ba32a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
