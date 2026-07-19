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

from ..schemas import (
    PurchaseOrderLineMutationCreate,
    PurchaseOrderLineMutationUpdate,
    PurchaseOrderLineRead,
)
from ..services import (
    create_purchase_order_line,
    delete_purchase_order_line,
    update_purchase_order_line,
)


router = APIRouter(
    tags=["purchase_management"]
)


@router.post(
    "/purchase/orders/{po_id}/lines",
    response_model=PurchaseOrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_order_line(
    po_id: int,
    payload: PurchaseOrderLineMutationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:update"
        )
    ),
):
    return create_purchase_order_line(
        db=db,
        user=current_user,
        po_id=po_id,
        data=payload.model_dump(),
    )


@router.patch(
    (
        "/purchase/orders/{po_id}/lines/"
        "{line_id}"
    ),
    response_model=PurchaseOrderLineRead,
)
def patch_order_line(
    po_id: int,
    line_id: int,
    payload: PurchaseOrderLineMutationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:update"
        )
    ),
):
    return update_purchase_order_line(
        db=db,
        user=current_user,
        po_id=po_id,
        line_id=line_id,
        data=payload.model_dump(
            exclude_unset=True
        ),
    )


@router.delete(
    (
        "/purchase/orders/{po_id}/lines/"
        "{line_id}"
    ),
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_order_line(
    po_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:update"
        )
    ),
):
    delete_purchase_order_line(
        db=db,
        user=current_user,
        po_id=po_id,
        line_id=line_id,
    )
