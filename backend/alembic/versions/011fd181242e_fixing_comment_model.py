"""fixing comment model

Revision ID: 011fd181242e
Revises: 4af9c0553bec
Create Date: 2025-11-29 09:33:04.611611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011fd181242e"
down_revision: Union[str, None] = "4af9c0553bec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name = '{table_name}'
                AND constraint_name = '{constraint_name}'
            ) THEN
                ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column("comments", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("comments", sa.Column("system_tag_id", sa.Integer(), nullable=True))
    op.add_column("comments", sa.Column("media_address", sa.String(), nullable=True))

    op.alter_column(
        "comments",
        "doc_id",
        existing_type=sa.INTEGER(),
        nullable=True,
    )

    op.create_index(op.f("ix_comments_chunk_id"), "comments", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_comments_doc_id"), "comments", ["doc_id"], unique=False)
    op.create_index(op.f("ix_comments_system_tag_id"), "comments", ["system_tag_id"], unique=False)
    op.create_index(op.f("ix_comments_user_id"), "comments", ["user_id"], unique=False)

    drop_constraint_if_exists("comments", "comments_doc_id_fkey")
    drop_constraint_if_exists("comments", "comments_chunk_id_fkey")
    drop_constraint_if_exists("comments", "fk_comments_system_tag_id_system_tags")
    drop_constraint_if_exists("comments", "fk_comments_chunk_id_chunks")
    drop_constraint_if_exists("comments", "fk_comments_doc_id_documents")
    drop_constraint_if_exists("comments", "fk_comments_user_id_users")
    drop_constraint_if_exists("documents", "documents_system_tag_id_fkey")
    drop_constraint_if_exists("documents", "fk_documents_system_tag_id_system_tags")
    drop_constraint_if_exists("users", "users_username_key")
    drop_constraint_if_exists("users", "uq_users_username")

    op.create_foreign_key(
        op.f("fk_comments_system_tag_id_system_tags"),
        "comments",
        "system_tags",
        ["system_tag_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_comments_chunk_id_chunks"),
        "comments",
        "chunks",
        ["chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_comments_doc_id_documents"),
        "comments",
        "documents",
        ["doc_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_comments_user_id_users"),
        "comments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    

    op.create_foreign_key(
        op.f("fk_documents_system_tag_id_system_tags"),
        "documents",
        "system_tags",
        ["system_tag_id"],
        ["id"],
        ondelete="CASCADE",
    )


    op.create_unique_constraint(op.f("uq_users_username"), "users", ["username"])


def downgrade() -> None:
    drop_constraint_if_exists("users", "uq_users_username")
    op.create_unique_constraint(op.f("users_username_key"), "users", ["username"])

    drop_constraint_if_exists("documents", "fk_documents_system_tag_id_system_tags")
    op.create_foreign_key(
        op.f("documents_system_tag_id_fkey"),
        "documents",
        "system_tags",
        ["system_tag_id"],
        ["id"],
    )

    drop_constraint_if_exists("comments", "fk_comments_user_id_users")
    drop_constraint_if_exists("comments", "fk_comments_doc_id_documents")
    drop_constraint_if_exists("comments", "fk_comments_chunk_id_chunks")
    drop_constraint_if_exists("comments", "fk_comments_system_tag_id_system_tags")

    op.create_foreign_key(
        op.f("comments_chunk_id_fkey"),
        "comments",
        "chunks",
        ["chunk_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("comments_doc_id_fkey"),
        "comments",
        "documents",
        ["doc_id"],
        ["id"],
    )

    op.drop_index(op.f("ix_comments_user_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_system_tag_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_doc_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_chunk_id"), table_name="comments")

    op.alter_column(
        "comments",
        "doc_id",
        existing_type=sa.INTEGER(),
        nullable=False,
    )

    op.drop_column("comments", "media_address")
    op.drop_column("comments", "system_tag_id")
    op.drop_column("comments", "user_id")