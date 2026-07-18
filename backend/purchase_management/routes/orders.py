"""Purchase order CRUD and approval routes."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    PurchaseOrderApproval,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderSummary,
    PurchaseOrderUpdate,
    ReceiptLinkCreate,
    ReceiptLinkRead,
)
from ..services import (
    add_receipt_link,
    cancel_purchase_order,
    create_purchase_order,
    create_purchase_order_from_rfq,
    get_po_or_404,
    get_summary,
    list_purchase_orders,
    process_approval,
    update_purchase_order,
)

router = APIRouter(tags=["purchase_management"])


@router.get(
    "/purchase/orders",
    response_model=List[PurchaseOrderRead],
)
def list_orders(
    status: Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:read")
    ),
):
    return list_purchase_orders(
        db=db,
        user=current_user,
        po_status=status,
        approval_status=approval_status,
        page=page,
        size=size,
    )


@router.post(
    "/purchase/orders",
    response_model=PurchaseOrderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:create")
    ),
):
    return create_purchase_order(
        db=db,
        user=current_user,
        data=payload.model_dump(),
    )


@router.post(
    "/purchase/orders/from-rfq/{rfq_id}",
    response_model=PurchaseOrderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_order_from_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:create")
    ),
    _rfq_reader: User = Depends(
        require_permission("rfq_management:read")
    ),
):
    return create_purchase_order_from_rfq(
        db=db,
        user=current_user,
        rfq_id=rfq_id,
    )


@router.get(
    "/purchase/orders/{po_id}",
    response_model=PurchaseOrderRead,
)
def get_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:read")
    ),
):
    return get_po_or_404(
        db=db,
        po_id=po_id,
        user=current_user,
    )


@router.patch(
    "/purchase/orders/{po_id}",
    response_model=PurchaseOrderRead,
)
def patch_order(
    po_id: int,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:update")
    ),
):
    return update_purchase_order(
        db=db,
        user=current_user,
        po_id=po_id,
        **payload.model_dump(exclude_unset=True),
    )


@router.delete(
    "/purchase/orders/{po_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:delete")
    ),
):
    cancel_purchase_order(
        db=db,
        user=current_user,
        po_id=po_id,
    )


@router.patch(
    "/purchase/orders/{po_id}/approval",
    response_model=PurchaseOrderRead,
)
def approval_action(
    po_id: int,
    payload: PurchaseOrderApproval,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:approve")
    ),
):
    return process_approval(
        db=db,
        user=current_user,
        po_id=po_id,
        action=payload.action,
        note=payload.note,
    )


@router.get(
    "/purchase/orders/{po_id}/summary",
    response_model=PurchaseOrderSummary,
)
def order_summary(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:summary")
    ),
):
    return get_summary(
        db=db,
        user=current_user,
        po_id=po_id,
    )


@router.post(
    "/purchase/orders/{po_id}/receipt-links",
    response_model=ReceiptLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def link_receipt(
    po_id: int,
    payload: ReceiptLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("purchase_management:orders:update")
    ),
):
    return add_receipt_link(
        db=db,
        user=current_user,
        po_id=po_id,
        financial_receipt_id=payload.financial_receipt_id,
    )
