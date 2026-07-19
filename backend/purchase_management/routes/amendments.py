from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..amendment_service import (
    decide_purchase_order_amendment,
    get_purchase_order_amendment,
    list_purchase_order_amendments,
    open_purchase_order_amendment,
    submit_purchase_order_amendment,
)
from ..schemas import (
    PurchaseOrderAmendmentCreate,
    PurchaseOrderAmendmentDecision,
    PurchaseOrderAmendmentRead,
    PurchaseOrderAmendmentSubmit,
)


router = APIRouter(
    tags=["purchase_management"]
)


@router.get(
    "/purchase/orders/{po_id}/amendments",
    response_model=list[
        PurchaseOrderAmendmentRead
    ],
)
def list_amendments(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:read"
        )
    ),
):
    return list_purchase_order_amendments(
        db=db,
        user=current_user,
        purchase_order_id=po_id,
    )


@router.post(
    "/purchase/orders/{po_id}/amendments",
    response_model=PurchaseOrderAmendmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_amendment(
    po_id: int,
    payload: PurchaseOrderAmendmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:amend"
        )
    ),
):
    return open_purchase_order_amendment(
        db=db,
        user=current_user,
        purchase_order_id=po_id,
        reason=payload.reason,
    )


@router.get(
    (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}"
    ),
    response_model=PurchaseOrderAmendmentRead,
)
def get_amendment(
    po_id: int,
    amendment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:read"
        )
    ),
):
    return get_purchase_order_amendment(
        db=db,
        user=current_user,
        purchase_order_id=po_id,
        amendment_id=amendment_id,
    )


@router.post(
    (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}/submit"
    ),
    response_model=PurchaseOrderAmendmentRead,
)
def submit_amendment(
    po_id: int,
    amendment_id: int,
    payload: PurchaseOrderAmendmentSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:submit"
        )
    ),
):
    return submit_purchase_order_amendment(
        db=db,
        user=current_user,
        purchase_order_id=po_id,
        amendment_id=amendment_id,
        note=payload.note,
    )


@router.patch(
    (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}/approval"
    ),
    response_model=PurchaseOrderAmendmentRead,
)
def decide_amendment(
    po_id: int,
    amendment_id: int,
    payload: PurchaseOrderAmendmentDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:approve"
        )
    ),
):
    return decide_purchase_order_amendment(
        db=db,
        user=current_user,
        purchase_order_id=po_id,
        amendment_id=amendment_id,
        action=payload.action,
        note=payload.note,
    )
