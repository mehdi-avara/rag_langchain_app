"""mineru s3 persistence and chunk images

Reshapes the (previously unused) ``image_chunks`` table to reference durable S3
objects, and records the derived ``mineru/`` prefix on documents and versions.

Revision ID: b1a2c3d4e5f6
Revises: 46a0f80fa1aa
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, None] = '46a0f80fa1aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- documents / document_versions: record derived mineru/ prefix ---
    op.add_column('documents', sa.Column('mineru_prefix', sa.String(), nullable=True))
    op.add_column('document_versions', sa.Column('mineru_prefix', sa.String(), nullable=True))

    # --- image_chunks: repurpose for S3-keyed figures ---
    # New columns (all nullable / additive).
    op.add_column('image_chunks', sa.Column('storage_key', sa.String(), nullable=True))
    op.add_column('image_chunks', sa.Column('page_num', sa.Integer(), nullable=True))
    op.add_column('image_chunks', sa.Column('bbox', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Relax / drop the old, unused columns. The table was never populated, so
    # there is no data to migrate.
    op.drop_column('image_chunks', 'image_data')
    op.alter_column('image_chunks', 'caption', existing_type=sa.Text(), nullable=True)
    op.alter_column('image_chunks', 'position', existing_type=sa.String(), nullable=True)

    op.create_index(op.f('ix_image_chunks_chunk_id'), 'image_chunks', ['chunk_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_image_chunks_chunk_id'), table_name='image_chunks')

    op.alter_column('image_chunks', 'position', existing_type=sa.String(), nullable=False)
    op.alter_column('image_chunks', 'caption', existing_type=sa.Text(), nullable=False)
    op.add_column('image_chunks', sa.Column('image_data', sa.Text(), nullable=False, server_default=''))
    op.alter_column('image_chunks', 'image_data', server_default=None)

    op.drop_column('image_chunks', 'bbox')
    op.drop_column('image_chunks', 'page_num')
    op.drop_column('image_chunks', 'storage_key')

    op.drop_column('document_versions', 'mineru_prefix')
    op.drop_column('documents', 'mineru_prefix')
