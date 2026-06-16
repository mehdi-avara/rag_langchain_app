"""Add document intelligence tables

Revision ID: a1b2c3d4e5f6
Revises: b5d91f0a7c33
Create Date: 2026-06-12 00:00:00.000000

Tables created
--------------
document_intelligence_jobs
document_page_artifacts
document_method_runs
document_segments
document_segment_suggestions
di_model_creation_suggestions
document_intelligence_labels
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b5d91f0a7c33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # document_intelligence_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "document_intelligence_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "triggered_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("methods_requested", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_document_intelligence_jobs_document_id",
        "document_intelligence_jobs",
        ["document_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # document_page_artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "document_page_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_num", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("text_hash", sa.String(64), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("thumbnail_path", sa.String(), nullable=True),
        sa.Column("image_hash", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("ocr_quality", sa.Float(), nullable=True),
        sa.Column("text_density", sa.Float(), nullable=True),
        sa.Column("image_density", sa.Float(), nullable=True),
        sa.Column("table_density", sa.Float(), nullable=True),
        sa.Column("layout_features", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "page_num", name="uq_di_page_artifact_doc_page"),
    )
    op.create_index(
        "ix_document_page_artifacts_document_id",
        "document_page_artifacts",
        ["document_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # document_method_runs
    # ------------------------------------------------------------------
    op.create_table(
        "document_method_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_seconds", sa.Float(), nullable=True),
        sa.Column("llm_tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("job_id", "method", name="uq_di_method_run_job_method"),
    )
    op.create_index(
        "ix_document_method_runs_job_id",
        "document_method_runs",
        ["job_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # document_segments
    # ------------------------------------------------------------------
    op.create_table(
        "document_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("detected_language", sa.String(10), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="predicted"),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "child_document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_di_segments_job_document",
        "document_segments",
        ["job_id", "document_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_segments_document_id",
        "document_segments",
        ["document_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # document_segment_suggestions
    # ------------------------------------------------------------------
    op.create_table(
        "document_segment_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "segment_id",
            sa.Integer(),
            sa.ForeignKey("document_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggestion_type", sa.String(), nullable=False),
        sa.Column("proposed_name", sa.String(), nullable=True),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_document_segment_suggestions_segment_id",
        "document_segment_suggestions",
        ["segment_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # di_model_creation_suggestions
    # ------------------------------------------------------------------
    op.create_table(
        "di_model_creation_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_pages", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "created_managed_model_id",
            sa.Integer(),
            sa.ForeignKey("managed_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_di_model_creation_suggestions_job_id",
        "di_model_creation_suggestions",
        ["job_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_di_model_creation_suggestions_document_id",
        "di_model_creation_suggestions",
        ["document_id"],
        if_not_exists=True,
    )

    # ------------------------------------------------------------------
    # document_intelligence_labels
    # ------------------------------------------------------------------
    op.create_table(
        "document_intelligence_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("document_intelligence_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gold_segments", sa.JSON(), nullable=False),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", name="uq_di_label_document"),
    )
    op.create_index(
        "ix_document_intelligence_labels_document_id",
        "document_intelligence_labels",
        ["document_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("document_intelligence_labels")
    op.drop_table("di_model_creation_suggestions")
    op.drop_table("document_segment_suggestions")
    op.drop_table("document_segments")
    op.drop_table("document_method_runs")
    op.drop_table("document_page_artifacts")
    op.drop_table("document_intelligence_jobs")
