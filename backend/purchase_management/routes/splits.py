from __future__ import annotations

from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    status,
)
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    PurchasePhaseSplitCandidate,
    PurchasePhaseSplitRequest,
    PurchasePhaseSplitResult,
)
from ..services import (
    get_purchase_order_split_candidates,
    split_purchase_order_phase,
)


router = APIRouter(
    tags=["purchase_management"]
)


@router.get(
    "/purchase/orders/{po_id}/split-candidates",
    response_model=list[
        PurchasePhaseSplitCandidate
    ],
)
def get_split_candidates(
    po_id: int,
    source_phase_id: Optional[int] = Query(
        None,
        gt=0,
    ),
    q: Optional[str] = Query(
        None,
        max_length=255,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:phases:split"
        )
    ),
):
    return get_purchase_order_split_candidates(
        db=db,
        user=current_user,
        po_id=po_id,
        source_phase_id=source_phase_id,
        query_text=q,
    )


@router.post(
    "/purchase/orders/{po_id}/phases/split",
    response_model=PurchasePhaseSplitResult,
    status_code=status.HTTP_201_CREATED,
)
def split_delivery_phase(
    po_id: int,
    payload: PurchasePhaseSplitRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:phases:split"
        )
    ),
):
    return split_purchase_order_phase(
        db=db,
        user=current_user,
        po_id=po_id,
        data=payload.model_dump(),
        idempotency_key=idempotency_key,
    )
