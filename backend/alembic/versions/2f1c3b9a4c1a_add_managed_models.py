"""add managed models

Revision ID: 2f1c3b9a4c1a
Revises: bd4fff6388cc
Create Date: 2026-02-07 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f1c3b9a4c1a'
down_revision: Union[str, None] = 'bd4fff6388cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'managed_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('manufacturer', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_managed_models_owner_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_managed_models')),
        sa.UniqueConstraint('manufacturer', 'model', name=op.f('uq_managed_models_manufacturer')),
    )
    op.create_index(op.f('ix_managed_models_manufacturer'), 'managed_models', ['manufacturer'], unique=False)
    op.create_index(op.f('ix_managed_models_model'), 'managed_models', ['model'], unique=False)
    op.create_index(op.f('ix_managed_models_type'), 'managed_models', ['type'], unique=False)

    op.create_table(
        'model_document_links',
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('linked_by_user_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_model_document_links_document_id_documents'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['linked_by_user_id'], ['users.id'], name=op.f('fk_model_document_links_linked_by_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['managed_models.id'], name=op.f('fk_model_document_links_model_id_managed_models'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('model_id', 'document_id', name=op.f('pk_model_document_links')),
    )
    op.create_index('ix_model_document_links_model_id', 'model_document_links', ['model_id'], unique=False)
    op.create_index('ix_model_document_links_document_id', 'model_document_links', ['document_id'], unique=False)

    op.create_table(
        'model_comment_links',
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('comment_id', sa.Integer(), nullable=False),
        sa.Column('linked_by_user_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['comment_id'], ['comments.id'], name=op.f('fk_model_comment_links_comment_id_comments'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['linked_by_user_id'], ['users.id'], name=op.f('fk_model_comment_links_linked_by_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['managed_models.id'], name=op.f('fk_model_comment_links_model_id_managed_models'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('model_id', 'comment_id', name=op.f('pk_model_comment_links')),
    )
    op.create_index('ix_model_comment_links_model_id', 'model_comment_links', ['model_id'], unique=False)
    op.create_index('ix_model_comment_links_comment_id', 'model_comment_links', ['comment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_model_comment_links_comment_id', table_name='model_comment_links')
    op.drop_index('ix_model_comment_links_model_id', table_name='model_comment_links')
    op.drop_table('model_comment_links')

    op.drop_index('ix_model_document_links_document_id', table_name='model_document_links')
    op.drop_index('ix_model_document_links_model_id', table_name='model_document_links')
    op.drop_table('model_document_links')

    op.drop_index(op.f('ix_managed_models_type'), table_name='managed_models')
    op.drop_index(op.f('ix_managed_models_model'), table_name='managed_models')
    op.drop_index(op.f('ix_managed_models_manufacturer'), table_name='managed_models')
    op.drop_table('managed_models')
