from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission
from shared.phase1_ask import answer_from_references, parse_citations

from ..search.schemas import RequisitionAskRequest, RequisitionAskResponse
from ..search.service import search_requisition_hits, validate_requisition_scope

router = APIRouter()


def _build_context(references) -> str:
    if not references:
        return "(no material requisition references)"

    return "\n".join(
        (
            f"[requisition:{item.requisition_id}] "
            f"number={item.mr_number} "
            f"status={item.status} "
            f"priority={item.priority} "
            f"needed_by_date={item.needed_by_date} "
            f"item_codes={','.join(item.item_codes) or '-'} "
            f"reason={item.reason}"
        )
        for item in references
    )


@router.post("/ask", response_model=RequisitionAskResponse)
async def ask_material_requisitions(
    payload: RequisitionAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:ask")
    ),
):
    requisition_ids = validate_requisition_scope(
        db,
        current_user,
        payload.requisition_ids,
    )

    references = search_requisition_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        requisition_ids=requisition_ids,
        limit=20,
    )

    if not references:
        return RequisitionAskResponse(
            answer="No matching material requisition references were found.",
            citations=[],
            used_requisition_ids=[],
            references=[],
        )

    answer = await answer_from_references(
        question=payload.question,
        references=references,
        context=_build_context(references),
        citation_prefix="requisition",
        component_name="requisition_management.ask",
    )

    return RequisitionAskResponse(
        answer=answer,
        citations=parse_citations(answer, "requisition"),
        used_requisition_ids=[
            item.requisition_id
            for item in references
        ],
        references=references,
    )
