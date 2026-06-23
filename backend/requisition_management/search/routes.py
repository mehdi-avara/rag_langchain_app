from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission

from .schemas import RequisitionSearchHit, RequisitionSearchRequest
from .service import search_requisition_hits, validate_requisition_scope

router = APIRouter()


@router.post("/search", response_model=list[RequisitionSearchHit])
def search_material_requisitions(
    payload: RequisitionSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("requisition_management:search")
    ),
):
    requisition_ids = validate_requisition_scope(
        db,
        current_user,
        payload.ids,
    )

    return search_requisition_hits(
        db=db,
        current_user=current_user,
        query_text=payload.query,
        mode=payload.mode,
        requisition_ids=requisition_ids,
        limit=payload.limit,
    )
