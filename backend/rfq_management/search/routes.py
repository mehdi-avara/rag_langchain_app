from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from .schemas import RFQSearchHit, RFQSearchRequest
from .service import search_rfq_hits, validate_rfq_scope

router = APIRouter()


@router.post("/search", response_model=list[RFQSearchHit])
def search_request_for_quotations(
    payload: RFQSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("rfq_management:search")
    ),
):
    rfq_ids = validate_rfq_scope(db, current_user, payload.ids)

    return search_rfq_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        rfq_ids=rfq_ids,
        limit=payload.limit,
    )
