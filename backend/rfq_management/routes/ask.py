from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission
from shared.phase1_ask import answer_from_references, parse_citations

from ..search.schemas import RFQAskRequest, RFQAskResponse
from ..search.service import search_rfq_hits, validate_rfq_scope

router = APIRouter()


def _build_context(references) -> str:
    if not references:
        return "(no RFQ references)"

    return "\n".join(
        (
            f"[rfq:{item.rfq_id}] "
            f"number={item.rfq_number} "
            f"status={item.status} "
            f"title={item.title} "
            f"deadline_date={item.deadline_date or '-'} "
            f"item_codes={','.join(item.item_codes) or '-'} "
            f"description={item.description or '-'}"
        )
        for item in references
    )


@router.post("/ask", response_model=RFQAskResponse)
async def ask_request_for_quotations(
    payload: RFQAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("rfq_management:ask")
    ),
):
    rfq_ids = validate_rfq_scope(db, current_user, payload.rfq_ids)

    references = search_rfq_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        rfq_ids=rfq_ids,
        limit=20,
    )

    if not references:
        return RFQAskResponse(
            answer="No matching RFQ references were found.",
            citations=[],
            used_rfq_ids=[],
            references=[],
        )

    answer = await answer_from_references(
        question=payload.question,
        references=references,
        context=_build_context(references),
        citation_prefix="rfq",
        component_name="rfq_management.ask",
    )

    return RFQAskResponse(
        answer=answer,
        citations=parse_citations(answer, "rfq"),
        used_rfq_ids=[item.rfq_id for item in references],
        references=references,
    )
