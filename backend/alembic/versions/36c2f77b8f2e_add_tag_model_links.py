"""add tag model links

Revision ID: 36c2f77b8f2e
Revises: 2f1c3b9a4c1a
Create Date: 2026-02-08 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36c2f77b8f2e'
down_revision: Union[str, None] = '2f1c3b9a4c1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tag_model_links',
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('linked_by_user_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['linked_by_user_id'], ['users.id'], name=op.f('fk_tag_model_links_linked_by_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['managed_models.id'], name=op.f('fk_tag_model_links_model_id_managed_models'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['system_tags.id'], name=op.f('fk_tag_model_links_tag_id_system_tags'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tag_id', 'model_id', name=op.f('pk_tag_model_links')),
    )
    op.create_index('ix_tag_model_links_tag_id', 'tag_model_links', ['tag_id'], unique=False)
    op.create_index('ix_tag_model_links_model_id', 'tag_model_links', ['model_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tag_model_links_model_id', table_name='tag_model_links')
    op.drop_index('ix_tag_model_links_tag_id', table_name='tag_model_links')
    op.drop_table('tag_model_links')
