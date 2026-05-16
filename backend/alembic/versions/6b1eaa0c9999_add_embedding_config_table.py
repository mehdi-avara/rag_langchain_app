"""add embedding config table

Revision ID: 6b1eaa0c9999
Revises: efb95510ae9c
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa

revision = '6b1eaa0c9999'
down_revision = 'efb95510ae9c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'embedding_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(length=255), nullable=False),
        sa.Column('base_url', sa.String(length=512), nullable=False),
        sa.Column('api_key', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('embedding_config')
