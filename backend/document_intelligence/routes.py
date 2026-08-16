from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from core.document_access import (
    get_accessible_document,
    get_accessible_document_ids,
)
from db.init_db import get_db
from deps import require_permission
from Models import Document, User
from document_intelligence.models import (
    DIJobStatus,
    DIModelCreationSuggestion,
    DISuggestionStatus,
    DISegmentStatus,
    DocumentIntelligenceJob,
    DocumentIntelligenceLabel,
    DocumentPageArtifact,
    DocumentSegment,
    DocumentSegmentSuggestion,
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


router = APIRouter(
    prefix="/document-intelligence",
    tags=["document-intelligence"],
)


def _get_job_or_404(
    db: Session,
    job_id: int,
) -> DocumentIntelligenceJob:
    job = (
        db.query(DocumentIntelligenceJob)
        .filter(
            DocumentIntelligenceJob.id == job_id
        )
        .first()
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job


def _get_accessible_job(
    db: Session,
    job_id: int,
    current_user: User,
    action: str,
) -> DocumentIntelligenceJob:
    job = _get_job_or_404(
        db,
        job_id,
    )

    get_accessible_document(
        db,
        job.document_id,
        current_user,
        action,
    )

    return job


def _get_segment_or_404(
    db: Session,
    segment_id: int,
) -> DocumentSegment:
    segment = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.id == segment_id
        )
        .first()
    )

    if not segment:
        raise HTTPException(
            status_code=404,
            detail="Segment not found",
        )

    return segment


def _get_accessible_segment(
    db: Session,
    segment_id: int,
    current_user: User,
    action: str,
) -> DocumentSegment:
    segment = _get_segment_or_404(
        db,
        segment_id,
    )

    get_accessible_document(
        db,
        segment.document_id,
        current_user,
        action,
    )

    return segment


def _get_segment_suggestion_or_404(
    db: Session,
    suggestion_id: int,
) -> DocumentSegmentSuggestion:
    suggestion = (
        db.query(DocumentSegmentSuggestion)
        .filter(
            DocumentSegmentSuggestion.id
            == suggestion_id
        )
        .first()
    )

    if not suggestion:
        raise HTTPException(
            status_code=404,
            detail="Suggestion not found",
        )

    return suggestion


def _get_accessible_segment_suggestion(
    db: Session,
    suggestion_id: int,
    current_user: User,
    action: str,
) -> DocumentSegmentSuggestion:
    suggestion = _get_segment_suggestion_or_404(
        db,
        suggestion_id,
    )

    _get_accessible_segment(
        db,
        suggestion.segment_id,
        current_user,
        action,
    )

    return suggestion


def _get_model_suggestion_or_404(
    db: Session,
    suggestion_id: int,
) -> DIModelCreationSuggestion:
    suggestion = (
        db.query(DIModelCreationSuggestion)
        .filter(
            DIModelCreationSuggestion.id
            == suggestion_id
        )
        .first()
    )

    if not suggestion:
        raise HTTPException(
            status_code=404,
            detail="Model creation suggestion not found",
        )

    return suggestion


def _get_accessible_model_suggestion(
    db: Session,
    suggestion_id: int,
    current_user: User,
    action: str,
) -> DIModelCreationSuggestion:
    suggestion = _get_model_suggestion_or_404(
        db,
        suggestion_id,
    )

    get_accessible_document(
        db,
        suggestion.document_id,
        current_user,
        action,
    )

    return suggestion


def _enqueue_job(
    job_id: int,
) -> None:
    try:
        from document_intelligence.tasks import (
            process_document_task,
        )

        process_document_task.delay(
            job_id
        )

    except Exception as exc:
        import logging

        logging.getLogger(
            __name__
        ).error(
            "Failed to enqueue job %d: %s",
            job_id,
            exc,
        )


@router.post(
    "/jobs",
    response_model=JobSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:update"
        )
    ),
):
    get_accessible_document(
        db,
        payload.document_id,
        current_user,
        "update",
    )

    job = DocumentIntelligenceJob(
        document_id=payload.document_id,
        triggered_by_user_id=current_user.id,
        status=DIJobStatus.QUEUED,
        methods_requested=payload.methods_requested,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _enqueue_job,
        job.id,
    )

    return job


@router.get(
    "/jobs",
    response_model=List[JobSummaryOut],
)
def list_jobs(
    document_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    accessible_document_ids = (
        get_accessible_document_ids(
            db,
            current_user,
            "read",
        )
    )

    query = (
        db.query(DocumentIntelligenceJob)
        .join(
            Document,
            Document.id
            == DocumentIntelligenceJob.document_id,
        )
        .join(
            User,
            User.id == Document.owner_id,
        )
        .filter(
            User.company_id
            == current_user.company_id
        )
    )

    if accessible_document_ids is not None:
        query = query.filter(
            DocumentIntelligenceJob.document_id.in_(
                accessible_document_ids
            )
        )

    if document_id is not None:
        get_accessible_document(
            db,
            document_id,
            current_user,
            "read",
        )

        query = query.filter(
            DocumentIntelligenceJob.document_id
            == document_id
        )

    return (
        query
        .order_by(
            DocumentIntelligenceJob.id.desc()
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobOut,
)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    return _get_accessible_job(
        db,
        job_id,
        current_user,
        "read",
    )


@router.get(
    "/documents/{doc_id}/jobs",
    response_model=List[JobSummaryOut],
)
def list_jobs_for_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    get_accessible_document(
        db,
        doc_id,
        current_user,
        "read",
    )

    return (
        db.query(DocumentIntelligenceJob)
        .filter(
            DocumentIntelligenceJob.document_id
            == doc_id
        )
        .order_by(
            DocumentIntelligenceJob.id.desc()
        )
        .all()
    )


@router.get(
    "/documents/{doc_id}/artifacts",
    response_model=List[PageArtifactOut],
)
def get_page_artifacts(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    get_accessible_document(
        db,
        doc_id,
        current_user,
        "read",
    )

    return (
        db.query(DocumentPageArtifact)
        .filter(
            DocumentPageArtifact.document_id
            == doc_id
        )
        .order_by(
            DocumentPageArtifact.page_num
        )
        .all()
    )


@router.get(
    "/documents/{doc_id}/segments",
    response_model=List[SegmentOut],
)
def list_segments_for_document(
    doc_id: int,
    job_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    get_accessible_document(
        db,
        doc_id,
        current_user,
        "read",
    )

    query = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.document_id
            == doc_id
        )
    )

    if job_id is not None:
        query = query.filter(
            DocumentSegment.job_id
            == job_id
        )

    return (
        query
        .order_by(
            DocumentSegment.start_page
        )
        .all()
    )


@router.get(
    "/segments/{segment_id}",
    response_model=SegmentOut,
)
def get_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    return _get_accessible_segment(
        db,
        segment_id,
        current_user,
        "read",
    )


@router.patch(
    "/segments/{segment_id}",
    response_model=SegmentOut,
)
def patch_segment(
    segment_id: int,
    payload: SegmentPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:update"
        )
    ),
):
    segment = _get_accessible_segment(
        db,
        segment_id,
        current_user,
        "update",
    )

    update_data = payload.model_dump(
        exclude_none=True
    )

    for field, value in update_data.items():
        setattr(
            segment,
            field,
            value,
        )

    if payload.status:
        segment.reviewed_by_user_id = (
            current_user.id
        )
        segment.reviewed_at = (
            datetime.utcnow()
        )

    db.commit()
    db.refresh(segment)

    return segment


@router.get(
    "/segments/{segment_id}/suggestions",
    response_model=List[SuggestionOut],
)
def list_suggestions_for_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    _get_accessible_segment(
        db,
        segment_id,
        current_user,
        "read",
    )

    return (
        db.query(DocumentSegmentSuggestion)
        .filter(
            DocumentSegmentSuggestion.segment_id
            == segment_id
        )
        .all()
    )


@router.patch(
    "/suggestions/{suggestion_id}",
    response_model=SuggestionOut,
)
def patch_suggestion(
    suggestion_id: int,
    payload: SuggestionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:update"
        )
    ),
):
    suggestion = (
        _get_accessible_segment_suggestion(
            db,
            suggestion_id,
            current_user,
            "update",
        )
    )

    if payload.status not in (
        DISuggestionStatus.ACCEPTED,
        DISuggestionStatus.REJECTED,
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "status must be "
                "'accepted' or 'rejected'"
            ),
        )

    suggestion.status = payload.status
    suggestion.reviewed_by_user_id = (
        current_user.id
    )
    suggestion.reviewed_at = (
        datetime.utcnow()
    )

    db.commit()
    db.refresh(suggestion)

    return suggestion


@router.get(
    "/jobs/{job_id}/model-suggestions",
    response_model=List[
        ModelCreationSuggestionOut
    ],
)
def list_model_creation_suggestions(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:read"
        )
    ),
):
    _get_accessible_job(
        db,
        job_id,
        current_user,
        "read",
    )

    return (
        db.query(
            DIModelCreationSuggestion
        )
        .filter(
            DIModelCreationSuggestion.job_id
            == job_id
        )
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
    current_user: User = Depends(
        require_permission(
            "documents:update"
        )
    ),
):
    suggestion = (
        _get_accessible_model_suggestion(
            db,
            suggestion_id,
            current_user,
            "update",
        )
    )

    if payload.status not in (
        DISuggestionStatus.ACCEPTED,
        DISuggestionStatus.REJECTED,
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "status must be "
                "'accepted' or 'rejected'"
            ),
        )

    suggestion.status = payload.status

    if payload.manufacturer is not None:
        suggestion.manufacturer = (
            payload.manufacturer
        )

    if payload.model_name is not None:
        suggestion.model_name = (
            payload.model_name
        )

    if payload.description is not None:
        suggestion.description = (
            payload.description
        )

    suggestion.reviewed_by_user_id = (
        current_user.id
    )
    suggestion.reviewed_at = (
        datetime.utcnow()
    )

    db.commit()
    db.refresh(suggestion)

    return suggestion


@router.get(
    "/jobs/{job_id}/export-labels",
    response_model=GoldLabelExport,
)
def export_gold_labels(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "documents:update"
        )
    ),
):
    job = _get_accessible_job(
        db,
        job_id,
        current_user,
        "update",
    )

    accepted_segments = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.job_id
            == job_id,
            DocumentSegment.status
            != DISegmentStatus.PREDICTED,
        )
        .order_by(
            DocumentSegment.start_page
        )
        .all()
    )

    gold_segments = []

    for segment in accepted_segments:
        accepted_suggestions = [
            {
                "type": suggestion.suggestion_type,
                "proposed_name": (
                    suggestion.proposed_name
                ),
                "manufacturer": (
                    suggestion.manufacturer
                ),
                "model_name": (
                    suggestion.model_name
                ),
                "target_id": suggestion.target_id,
                "confidence": (
                    suggestion.confidence
                ),
                "evidence": suggestion.evidence,
            }
            for suggestion in segment.suggestions
            if suggestion.status
            == DISuggestionStatus.ACCEPTED
        ]

        gold_segments.append(
            {
                "start_page": (
                    segment.start_page
                ),
                "end_page": segment.end_page,
                "title": segment.title,
                "document_type": (
                    segment.document_type
                ),
                "summary": segment.summary,
                "detected_language": (
                    segment.detected_language
                ),
                "confidence": (
                    segment.confidence
                ),
                "evidence": (
                    segment.evidence or []
                ),
                "suggestions": (
                    accepted_suggestions
                ),
                "reviewer_status": (
                    segment.status
                ),
            }
        )

    label = (
        db.query(
            DocumentIntelligenceLabel
        )
        .filter(
            DocumentIntelligenceLabel.document_id
            == job.document_id
        )
        .first()
    )

    if label is None:
        label = DocumentIntelligenceLabel(
            document_id=job.document_id,
            job_id=job_id,
            gold_segments=gold_segments,
            created_by_user_id=(
                current_user.id
            ),
        )

        db.add(label)

    else:
        label.job_id = job_id
        label.gold_segments = (
            gold_segments
        )
        label.exported_at = (
            datetime.utcnow()
        )

    db.commit()

    return GoldLabelExport(
        document_id=job.document_id,
        job_id=job_id,
        gold_segments=gold_segments,
    )
