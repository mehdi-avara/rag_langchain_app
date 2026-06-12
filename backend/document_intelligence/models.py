"""
SQLAlchemy models for Document Intelligence module.

Tables
------
document_intelligence_jobs        - One job per (document, trigger).
document_page_artifacts            - Cached per-page text / image / features.
document_method_runs               - Raw output blob from one method run.
document_segments                  - Predicted / reviewed logical segments.
document_segment_suggestions       - Tag / model / process suggestions per segment.
di_model_creation_suggestions      - Unknown-model candidates (never auto-created).
document_intelligence_labels       - Human-approved gold labels for training export.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DIJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DIMethod(str, enum.Enum):
    LLM_VLM = "llm_vlm"
    TEXT_EMBEDDING = "text_embedding"
    IMAGE_PROCESSING = "image_processing"
    FUSION = "fusion"


class DISegmentStatus(str, enum.Enum):
    PREDICTED = "predicted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"


class DISuggestionType(str, enum.Enum):
    TAG = "tag"
    MANAGED_MODEL = "managed_model"
    PROCESS_LINK = "process_link"
    CATEGORY = "category"


class DISuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DIDocumentType(str, enum.Enum):
    MANUAL = "manual"
    DATASHEET = "datasheet"
    CERTIFICATE = "certificate"
    CALIBRATION = "calibration"
    INVOICE = "invoice"
    REPORT = "report"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# document_intelligence_jobs
# ---------------------------------------------------------------------------

class DocumentIntelligenceJob(Base):
    """One analysis job for one document.  A document may have many jobs
    (e.g. re-runs after human correction)."""

    __tablename__ = "document_intelligence_jobs"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default=DIJobStatus.QUEUED)
    error_message = Column(Text, nullable=True)
    # Which methods to run (JSON list: ["llm_vlm", "text_embedding", ...])
    methods_requested = Column(JSON, nullable=False, default=["llm_vlm"])
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    document = relationship("Document")
    triggered_by = relationship("User", foreign_keys=[triggered_by_user_id])
    method_runs = relationship(
        "DocumentMethodRun",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    segments = relationship(
        "DocumentSegment",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ---------------------------------------------------------------------------
# document_page_artifacts
# ---------------------------------------------------------------------------

class DocumentPageArtifact(Base):
    """Cached per-page data (text, image path, hashes, features).
    Re-used across all method runs so we never re-render the same page."""

    __tablename__ = "document_page_artifacts"
    __table_args__ = (
        UniqueConstraint("document_id", "page_num", name="uq_di_page_artifact_doc_page"),
    )

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_num = Column(Integer, nullable=False)          # 1-based

    # Text
    text = Column(Text, nullable=True)                  # MinerU / pdfminer text
    ocr_text = Column(Text, nullable=True)              # Tesseract fallback
    text_hash = Column(String(64), nullable=True)       # sha256 of text

    # Images
    image_path = Column(String, nullable=True)          # relative path to full-res PNG
    thumbnail_path = Column(String, nullable=True)      # relative path to thumbnail PNG
    image_hash = Column(String(64), nullable=True)      # perceptual hash (phash hex)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # Quality / density signals
    ocr_quality = Column(Float, nullable=True)          # 0-1 confidence from pytesseract
    text_density = Column(Float, nullable=True)         # chars / pixel
    image_density = Column(Float, nullable=True)        # image area / page area
    table_density = Column(Float, nullable=True)        # estimated table area / page area

    # Layout features JSON (arbitrary dict for classifiers)
    layout_features = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document")


# ---------------------------------------------------------------------------
# document_method_runs
# ---------------------------------------------------------------------------

class DocumentMethodRun(Base):
    """Raw structured output (JSON) from one method for one job.
    Preserves method-level results independently so we can compare them."""

    __tablename__ = "document_method_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "method", name="uq_di_method_run_job_method"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(
        Integer,
        ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method = Column(String, nullable=False)             # DIMethod value
    status = Column(String, nullable=False, default="pending")
    # Full canonical output dict stored as JSON
    output = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    latency_seconds = Column(Float, nullable=True)
    llm_tokens_used = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    job = relationship("DocumentIntelligenceJob", back_populates="method_runs")


# ---------------------------------------------------------------------------
# document_segments
# ---------------------------------------------------------------------------

class DocumentSegment(Base):
    """One logical document within the parent PDF, spanning start_page..end_page.
    Initially predicted by a method; later accepted/modified/rejected by a reviewer."""

    __tablename__ = "document_segments"

    id = Column(Integer, primary_key=True)
    job_id = Column(
        Integer,
        ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method = Column(String, nullable=False)             # which method produced this
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)

    # Classification
    title = Column(String, nullable=True)
    document_type = Column(String, nullable=True)       # DIDocumentType value
    summary = Column(Text, nullable=True)
    detected_language = Column(String(10), nullable=True)
    confidence = Column(Float, nullable=True)

    # Evidence (list of {page, kind, value})
    evidence = Column(JSON, nullable=True)

    # Review
    status = Column(String, nullable=False, default=DISegmentStatus.PREDICTED)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime, nullable=True)

    # If accepted → optionally linked to a child Document
    child_document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    job = relationship("DocumentIntelligenceJob", back_populates="segments")
    document = relationship("Document", foreign_keys=[document_id])
    child_document = relationship("Document", foreign_keys=[child_document_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])
    suggestions = relationship(
        "DocumentSegmentSuggestion",
        back_populates="segment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


Index(
    "ix_di_segments_job_document",
    DocumentSegment.job_id,
    DocumentSegment.document_id,
)


# ---------------------------------------------------------------------------
# document_segment_suggestions
# ---------------------------------------------------------------------------

class DocumentSegmentSuggestion(Base):
    """One suggestion (tag / managed_model / process_link / category) for a segment."""

    __tablename__ = "document_segment_suggestions"

    id = Column(Integer, primary_key=True)
    segment_id = Column(
        Integer,
        ForeignKey("document_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggestion_type = Column(String, nullable=False)    # DISuggestionType value
    proposed_name = Column(String, nullable=True)       # tag / process name
    manufacturer = Column(String, nullable=True)        # for managed_model suggestions
    model_name = Column(String, nullable=True)          # for managed_model suggestions
    target_id = Column(Integer, nullable=True)          # existing Tag/ManagedModel id if matched
    confidence = Column(Float, nullable=True)
    evidence = Column(Text, nullable=True)
    status = Column(String, nullable=False, default=DISuggestionStatus.PENDING)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    segment = relationship("DocumentSegment", back_populates="suggestions")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])


# ---------------------------------------------------------------------------
# di_model_creation_suggestions
# ---------------------------------------------------------------------------

class DIModelCreationSuggestion(Base):
    """Unknown-model candidate.  Never creates a real ManagedModel automatically.
    Requires explicit user approval before anything is persisted."""

    __tablename__ = "di_model_creation_suggestions"

    id = Column(Integer, primary_key=True)
    job_id = Column(
        Integer,
        ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manufacturer = Column(String, nullable=True)
    model_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    evidence_text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    # Pages where this candidate was spotted (JSON list of ints)
    evidence_pages = Column(JSON, nullable=True)

    status = Column(String, nullable=False, default=DISuggestionStatus.PENDING)
    # If accepted, link to the created ManagedModel
    created_managed_model_id = Column(
        Integer,
        ForeignKey("managed_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    job = relationship("DocumentIntelligenceJob")
    document = relationship("Document", foreign_keys=[document_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])


# ---------------------------------------------------------------------------
# document_intelligence_labels  (gold-label export for training)
# ---------------------------------------------------------------------------

class DocumentIntelligenceLabel(Base):
    """Human-approved gold label for one document.  Used to export training datasets."""

    __tablename__ = "document_intelligence_labels"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_di_label_document"),
    )

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        Integer,
        ForeignKey("document_intelligence_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Full gold output in canonical segment schema (JSON)
    gold_segments = Column(JSON, nullable=False)
    exported_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
