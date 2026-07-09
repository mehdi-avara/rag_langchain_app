"""Assistant FastAPI endpoints (PROMPT §4).

- ``POST /assistant/chat``                  — agentic, SSE-streamed; may return a Draft. Never commits.
- ``GET  /assistant/drafts/{id}``           — fetch/resume a draft.
- ``PATCH /assistant/drafts/{id}``          — edit fields on the assistant-side copy.
- ``POST /assistant/drafts/{id}/committed`` — record-only notification (writes no domain data).
- ``POST /assistant/drafts/{id}/cancel``    — discard.

There is deliberately **no** ``/confirm`` write endpoint: the commit is the
frontend POSTing the final payload to ``draft.commit_target.endpoint`` (the
module's own create/update route).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

# Ensure module toolsets are registered into the intent registry.
import financial_management.assistant_tools  # noqa: F401
import goods_receipt_management.assistant_tools  # noqa: F401
import material_management.assistant_tools  # noqa: F401
import purchase_management.assistant_tools  # noqa: F401
import requisition_management.assistant_tools  # noqa: F401
import rfq_management.assistant_tools  # noqa: F401
import supplier_management.assistant_tools  # noqa: F401
import warehouse_management.assistant_tools  # noqa: F401
from db.init_db import get_db
from deps import require_permission
from Models import User

from . import service as draft_service
from .runner import run_turn_stream
from .schemas import (
    AssistantChatRequest,
    DraftCommittedRequest,
    DraftOut,
    DraftPatchRequest,
)

router = APIRouter()


@router.post("/chat")
async def assistant_chat(
    request: AssistantChatRequest,
    current_user: User = Depends(require_permission("assistant:chat")),
    db: Session = Depends(get_db),
):
    generator = await run_turn_stream(db, user=current_user, request=request)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: int,
    current_user: User = Depends(require_permission("assistant:draft")),
    db: Session = Depends(get_db),
):
    draft = draft_service.get_draft(db, draft_id=draft_id, user=current_user)
    return DraftOut.model_validate(draft)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def patch_draft(
    draft_id: int,
    payload: DraftPatchRequest,
    current_user: User = Depends(require_permission("assistant:draft")),
    db: Session = Depends(get_db),
):
    draft = draft_service.get_draft(db, draft_id=draft_id, user=current_user)
    draft = draft_service.patch_draft(
        db,
        draft=draft,
        payload=payload.payload,
        resolved_references=payload.resolved_references,
    )
    return DraftOut.model_validate(draft)


@router.post("/drafts/{draft_id}/committed", response_model=DraftOut)
def draft_committed(
    draft_id: int,
    payload: DraftCommittedRequest,
    current_user: User = Depends(require_permission("assistant:draft")),
    db: Session = Depends(get_db),
):
    """Record-only: the frontend already wrote via the module endpoint (§4.1).

    This endpoint writes NO domain data and re-checks NO domain permission.
    """
    draft = draft_service.get_draft(db, draft_id=draft_id, user=current_user)
    draft = draft_service.record_committed(
        db, draft=draft, user=current_user, committed_entity_ref=payload.committed_entity_ref
    )
    return DraftOut.model_validate(draft)


@router.post("/drafts/{draft_id}/cancel", response_model=DraftOut)
def draft_cancel(
    draft_id: int,
    current_user: User = Depends(require_permission("assistant:draft")),
    db: Session = Depends(get_db),
):
    draft = draft_service.get_draft(db, draft_id=draft_id, user=current_user)
    draft = draft_service.cancel_draft(db, draft=draft)
    return DraftOut.model_validate(draft)
