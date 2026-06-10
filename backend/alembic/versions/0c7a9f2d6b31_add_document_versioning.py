"""add document versioning

Revision ID: 0c7a9f2d6b31
Revises: f6a1c9e2d4b7
Create Date: 2026-06-10 15:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0c7a9f2d6b31"
down_revision: Union[str, None] = "f6a1c9e2d4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("n_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["asset_id"], ["file_assets.id"], name=op.f("fk_document_versions_asset_id_file_assets"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_document_versions_created_by_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_versions_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_id_version_number"),
    )

    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_versions_asset_id"), "document_versions", ["asset_id"], unique=False)
    op.create_index(op.f("ix_document_versions_created_by_user_id"), "document_versions", ["created_by_user_id"], unique=False)

    op.add_column("documents", sa.Column("current_version_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_documents_current_version_id"), "documents", ["current_version_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_documents_current_version_id_document_versions"),
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("chunks", sa.Column("document_version_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_chunks_document_version_id"), "chunks", ["document_version_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_chunks_document_version_id_document_versions"),
        "chunks",
        "document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        """
        INSERT INTO document_versions (
            document_id,
            version_number,
            asset_id,
            filename,
            file_path,
            status,
            n_pages,
            n_chunks,
            created_by_user_id,
            note,
            is_current,
            created_at
        )
        SELECT
            d.id,
            1,
            d.original_asset_id,
            d.filename,
            d.file_path,
            d.status,
            d.n_pages,
            d.n_chunks,
            d.owner_id,
            'Initial version migrated from existing document',
            true,
            d.created_at
        FROM documents d
        WHERE NOT EXISTS (
            SELECT 1
            FROM document_versions dv
            WHERE dv.document_id = d.id
              AND dv.version_number = 1
        )
        """
    )

    op.execute(
        """
        UPDATE documents d
        SET current_version_id = dv.id
        FROM document_versions dv
        WHERE dv.document_id = d.id
          AND dv.version_number = 1
          AND d.current_version_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE chunks c
        SET document_version_id = dv.id
        FROM document_versions dv
        WHERE dv.document_id = c.doc_id
          AND dv.version_number = 1
          AND c.document_version_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_chunks_document_version_id_document_versions"), "chunks", type_="foreignkey")
    op.drop_index(op.f("ix_chunks_document_version_id"), table_name="chunks")
    op.drop_column("chunks", "document_version_id")

    op.drop_constraint(op.f("fk_documents_current_version_id_document_versions"), "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_current_version_id"), table_name="documents")
    op.drop_column("documents", "current_version_id")

    op.drop_index(op.f("ix_document_versions_created_by_user_id"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_asset_id"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")
