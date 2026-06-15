"""
Pydantic schemas for Document Intelligence API.
All response models mirror the canonical segment output contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared leaf types
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    page: int
    kind: str = Field(..., description="text | visual | layout")
    value: str


class SuggestionOut(BaseModel):
    id: int
    segment_id: int
    suggestion_type: str
    proposed_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model_name: Optional[str] = None
    target_id: Optional[int] = None
    confidence: Optional[float] = None
    evidence: Optional[str] = None
    status: str
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SuggestionPatch(BaseModel):
    status: str = Field(..., description="accepted | rejected")


# ---------------------------------------------------------------------------
# Segment schemas
# ---------------------------------------------------------------------------

class SegmentOut(BaseModel):
    id: int
    job_id: int
    document_id: int
    method: str
    start_page: int
    end_page: int
    title: Optional[str] = None
    document_type: Optional[str] = None
    summary: Optional[str] = None
    detected_language: Optional[str] = None
    confidence: Optional[float] = None
    evidence: Optional[List[EvidenceItem]] = None
    status: str
    reviewed_at: Optional[datetime] = None
    child_document_id: Optional[int] = None
    suggestions: List[SuggestionOut] = []
    created_at: datetime

    class Config:
        from_attributes = True


class SegmentPatch(BaseModel):
    status: Optional[str] = None            # accepted | rejected | modified
    title: Optional[str] = None
    document_type: Optional[str] = None
    summary: Optional[str] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None


# ---------------------------------------------------------------------------
# Job schemas
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    document_id: int
    methods_requested: List[str] = Field(
        default=["llm_vlm"],
        description="One or more of: llm_vlm, text_embedding, image_processing, fusion",
    )


class MethodRunOut(BaseModel):
    id: int
    job_id: int
    method: str
    status: str
    latency_seconds: Optional[float] = None
    llm_tokens_used: Optional[int] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: int
    document_id: int
    status: str
    methods_requested: List[str]
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    method_runs: List[MethodRunOut] = []
    segments: List[SegmentOut] = []

    class Config:
        from_attributes = True


class JobSummaryOut(BaseModel):
    id: int
    document_id: int
    status: str
    methods_requested: List[str]
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Page artifact schemas
# ---------------------------------------------------------------------------

class PageArtifactOut(BaseModel):
    id: int
    document_id: int
    page_num: int
    text: Optional[str] = None
    text_hash: Optional[str] = None
    image_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    image_hash: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    ocr_quality: Optional[float] = None
    text_density: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Model-creation suggestion schemas
# ---------------------------------------------------------------------------

class ModelCreationSuggestionOut(BaseModel):
    id: int
    job_id: int
    document_id: int
    manufacturer: Optional[str] = None
    model_name: str
    description: Optional[str] = None
    evidence_text: Optional[str] = None
    confidence: Optional[float] = None
    evidence_pages: Optional[List[int]] = None
    status: str
    created_managed_model_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ModelCreationSuggestionPatch(BaseModel):
    status: str = Field(..., description="accepted | rejected")
    # When accepting, caller may supply these overrides before the model is created.
    manufacturer: Optional[str] = None
    model_name: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Gold-label export schema
# ---------------------------------------------------------------------------

class GoldLabelExport(BaseModel):
    document_id: int
    job_id: Optional[int] = None
    gold_segments: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Canonical method output (internal contract, not returned to user directly)
# ---------------------------------------------------------------------------

class CanonicalSuggestionPayload(BaseModel):
    type: str                               # DISuggestionType
    proposed_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    target_id: Optional[int] = None
    confidence: float
    evidence: str


class CanonicalSegmentPayload(BaseModel):
    start_page: int
    end_page: int
    title: Optional[str] = None
    document_type: str = "unknown"
    summary: Optional[str] = None
    detected_language: Optional[str] = "en"
    confidence: float = 0.0
    evidence: List[EvidenceItem] = []
    suggestions: List[CanonicalSuggestionPayload] = []


class CanonicalMethodOutput(BaseModel):
    document_id: int
    method: str
    segments: List[CanonicalSegmentPayload]
