"""
FastAPI routes for Document Intelligence.

Prefix: /document-intelligence

Endpoints
---------
POST   /jobs                                       – Create & enqueue a new job
GET    /jobs/{job_id}                              – Get job detail + segments
GET    /jobs                                       – List jobs (optionally filter by document)
GET    /documents/{doc_id}/jobs                    – All jobs for a document
GET    /documents/{doc_id}/artifacts               – Page artifacts for a document
GET    /segments/{segment_id}                      – Single segment detail
PATCH  /segments/{segment_id}                      – Review a segment (accept/reject/modify)
PATCH  /suggestions/{suggestion_id}                – Review a suggestion
GET    /jobs/{job_id}/model-suggestions            – Unknown-model candidates for a job
PATCH  /model-suggestions/{suggestion_id}          – Review a model-creation suggestion
GET    /jobs/{job_id}/export-labels                – Export gold labels for training
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import Document, User
from document_intelligence.models import (
    DIJobStatus,
    DIMethod,
    DIModelCreationSuggestion,
    DISuggestionStatus,
    DocumentIntelligenceJob,
    DocumentIntelligenceLabel,
    DocumentMethodRun,
    DocumentPageArtifact,
    DocumentSegment,
    DocumentSegmentSuggestion,
    DISegmentStatus,
)
from document_intelligence.schemas import (
    GoldLabelExport,
    JobCreate,
    JobOut,
    JobSummaryOut,
    ModelCreationSuggestionOut,
    ModelCreationSuggestionPatch,
    PageArtifactOut,
    SegmentOut,
    SegmentPatch,
    SuggestionOut,
    SuggestionPatch,
)

router = APIRouter(prefix="/document-intelligence", tags=["document-intelligence"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_document_or_404(db: Session, doc_id: int) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _get_job_or_404(db: Session, job_id: int) -> DocumentIntelligenceJob:
    job = db.query(DocumentIntelligenceJob).filter(
        DocumentIntelligenceJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _enqueue_job(job_id: int) -> None:
    """Send the job to Celery.  Import here to avoid circular imports at module load."""
    try:
        from document_intelligence.tasks import process_document_task
        process_document_task.delay(job_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Failed to enqueue job %d: %s", job_id, exc
        )


# ---------------------------------------------------------------------------
# Job endpoints
# ---------------------------------------------------------------------------

@router.post("/jobs", response_model=JobSummaryOut, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new Document Intelligence job and enqueue it."""
    _get_document_or_404(db, payload.document_id)

    job = DocumentIntelligenceJob(
        document_id=payload.document_id,
        triggered_by_user_id=current_user.id,
        status=DIJobStatus.QUEUED,
        methods_requested=payload.methods_requested,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_enqueue_job, job.id)
    return job


@router.get("/jobs", response_model=List[JobSummaryOut])
def list_jobs(
    document_id: Optional[int] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List Document Intelligence jobs, optionally filtered by document."""
    q = db.query(DocumentIntelligenceJob)
    if document_id is not None:
        q = q.filter(DocumentIntelligenceJob.document_id == document_id)
    return q.order_by(DocumentIntelligenceJob.id.desc()).offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full job detail including method runs and segments."""
    job = _get_job_or_404(db, job_id)
    return job


@router.get("/documents/{doc_id}/jobs", response_model=List[JobSummaryOut])
def list_jobs_for_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_document_or_404(db, doc_id)
    return (
        db.query(DocumentIntelligenceJob)
        .filter(DocumentIntelligenceJob.document_id == doc_id)
        .order_by(DocumentIntelligenceJob.id.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Page artifact endpoints
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/artifacts", response_model=List[PageArtifactOut])
def get_page_artifacts(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_document_or_404(db, doc_id)
    return (
        db.query(DocumentPageArtifact)
        .filter(DocumentPageArtifact.document_id == doc_id)
        .order_by(DocumentPageArtifact.page_num)
        .all()
    )


# ---------------------------------------------------------------------------
# Segment endpoints
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/segments", response_model=List[SegmentOut])
def list_segments_for_document(
    doc_id: int,
    job_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List segments for a document, optionally filtered to one job."""
    _get_document_or_404(db, doc_id)
    q = db.query(DocumentSegment).filter(DocumentSegment.document_id == doc_id)
    if job_id is not None:
        q = q.filter(DocumentSegment.job_id == job_id)
    return q.order_by(DocumentSegment.start_page).all()


@router.get("/segments/{segment_id}", response_model=SegmentOut)
def get_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    seg = db.query(DocumentSegment).filter(DocumentSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")
    return seg


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def patch_segment(
    segment_id: int,
    payload: SegmentPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept, reject, or modify a predicted segment."""
    seg = db.query(DocumentSegment).filter(DocumentSegment.id == segment_id).first()
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(seg, field, value)

    if payload.status:
        seg.reviewed_by_user_id = current_user.id
        seg.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(seg)
    return seg


# ---------------------------------------------------------------------------
# Suggestion endpoints
# ---------------------------------------------------------------------------

@router.get("/segments/{segment_id}/suggestions", response_model=List[SuggestionOut])
def list_suggestions_for_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(DocumentSegmentSuggestion)
        .filter(DocumentSegmentSuggestion.segment_id == segment_id)
        .all()
    )


@router.patch("/suggestions/{suggestion_id}", response_model=SuggestionOut)
def patch_suggestion(
    suggestion_id: int,
    payload: SuggestionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept or reject a suggestion."""
    sug = (
        db.query(DocumentSegmentSuggestion)
        .filter(DocumentSegmentSuggestion.id == suggestion_id)
        .first()
    )
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if payload.status not in (DISuggestionStatus.ACCEPTED, DISuggestionStatus.REJECTED):
        raise HTTPException(
            status_code=422,
            detail="status must be 'accepted' or 'rejected'",
        )

    sug.status = payload.status
    sug.reviewed_by_user_id = current_user.id
    sug.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(sug)
    return sug


# ---------------------------------------------------------------------------
# Model-creation suggestion endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/model-suggestions",
    response_model=List[ModelCreationSuggestionOut],
)
def list_model_creation_suggestions(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_job_or_404(db, job_id)
    return (
        db.query(DIModelCreationSuggestion)
        .filter(DIModelCreationSuggestion.job_id == job_id)
        .all()
    )


@router.patch(
    "/model-suggestions/{suggestion_id}",
    response_model=ModelCreationSuggestionOut,
)
def patch_model_creation_suggestion(
    suggestion_id: int,
    payload: ModelCreationSuggestionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Accept or reject an unknown-model candidate.
    Accepting does NOT automatically create a ManagedModel – that requires a
    separate action from the model management module.
    """
    sug = (
        db.query(DIModelCreationSuggestion)
        .filter(DIModelCreationSuggestion.id == suggestion_id)
        .first()
    )
    if not sug:
        raise HTTPException(status_code=404, detail="Model creation suggestion not found")

    if payload.status not in (DISuggestionStatus.ACCEPTED, DISuggestionStatus.REJECTED):
        raise HTTPException(
            status_code=422,
            detail="status must be 'accepted' or 'rejected'",
        )

    sug.status = payload.status
    if payload.manufacturer is not None:
        sug.manufacturer = payload.manufacturer
    if payload.model_name is not None:
        sug.model_name = payload.model_name
    if payload.description is not None:
        sug.description = payload.description

    sug.reviewed_by_user_id = current_user.id
    sug.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(sug)
    return sug


# ---------------------------------------------------------------------------
# Gold-label export
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/export-labels", response_model=GoldLabelExport)
def export_gold_labels(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export human-approved (accepted/modified) segments as a gold-label dataset.
    Only segments with status != 'predicted' are included.
    """
    job = _get_job_or_404(db, job_id)

    accepted_segments = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.job_id == job_id,
            DocumentSegment.status != DISegmentStatus.PREDICTED,
        )
        .order_by(DocumentSegment.start_page)
        .all()
    )

    gold_segments = []
    for seg in accepted_segments:
        # Collect accepted suggestions
        accepted_sugs = [
            {
                "type": sug.suggestion_type,
                "proposed_name": sug.proposed_name,
                "manufacturer": sug.manufacturer,
                "model_name": sug.model_name,
                "target_id": sug.target_id,
                "confidence": sug.confidence,
                "evidence": sug.evidence,
            }
            for sug in seg.suggestions
            if sug.status == DISuggestionStatus.ACCEPTED
        ]

        gold_segments.append(
            {
                "start_page": seg.start_page,
                "end_page": seg.end_page,
                "title": seg.title,
                "document_type": seg.document_type,
                "summary": seg.summary,
                "detected_language": seg.detected_language,
                "confidence": seg.confidence,
                "evidence": seg.evidence or [],
                "suggestions": accepted_sugs,
                "reviewer_status": seg.status,
            }
        )

    # Upsert a DocumentIntelligenceLabel row
    label = (
        db.query(DocumentIntelligenceLabel)
        .filter(DocumentIntelligenceLabel.document_id == job.document_id)
        .first()
    )
    if label is None:
        label = DocumentIntelligenceLabel(
            document_id=job.document_id,
            job_id=job_id,
            gold_segments=gold_segments,
            created_by_user_id=current_user.id,
        )
        db.add(label)
    else:
        label.job_id = job_id
        label.gold_segments = gold_segments
        label.exported_at = datetime.utcnow()

    db.commit()

    return GoldLabelExport(
        document_id=job.document_id,
        job_id=job_id,
        gold_segments=gold_segments,
    )
