"""cascade delete chunks when document deleted

Revision ID: 9ea390ba32a0
Revises: 94e21481b093
Create Date: 2026-02-23 08:34:37.561910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ea390ba32a0'
down_revision: Union[str, None] = '94e21481b093'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chunks") as batch:
        batch.drop_constraint(op.f("fk_chunks_doc_id_documents"), type_="foreignkey")
        batch.create_foreign_key(
            op.f("fk_chunks_doc_id_documents"),
            "documents",
            ["doc_id"],
            ["id"],
            ondelete="CASCADE",
        )

def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch:
        batch.drop_constraint(op.f("fk_chunks_doc_id_documents"), type_="foreignkey")
        batch.create_foreign_key(
            op.f("fk_chunks_doc_id_documents"),
            "documents",
            ["doc_id"],
            ["id"],
        )