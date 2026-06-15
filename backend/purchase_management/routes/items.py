"""Phase item routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import PurchasePhaseItemCreate, PurchasePhaseItemRead, PurchasePhaseItemUpdate
from ..services import add_phase_item, update_phase_item

router = APIRouter(tags=["purchase_management"])


@router.post(
    "/purchase/orders/{po_id}/phases/{phase_id}/items",
    response_model=PurchasePhaseItemRead,
    status_code=201,
)
def create_item(
    po_id: int,
    phase_id: int,
    payload: PurchasePhaseItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:phases:manage")),
):
    return add_phase_item(
        db, current_user, po_id, phase_id,
        item_name=payload.item_name,
        item_code=payload.item_code,
        quantity=payload.quantity,
        unit=payload.unit,
        unit_price=payload.unit_price,
        currency_id=payload.currency_id,
        unit_price_base=payload.unit_price_base,
        base_currency_id=payload.base_currency_id,
        exchange_rate_used=payload.exchange_rate_used,
        notes=payload.notes,
    )


@router.patch(
    "/purchase/orders/{po_id}/phases/{phase_id}/items/{item_id}",
    response_model=PurchasePhaseItemRead,
)
def patch_item(
    po_id: int,
    phase_id: int,
    item_id: int,
    payload: PurchasePhaseItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:phases:manage")),
):
    return update_phase_item(
        db, current_user, po_id, phase_id, item_id,
        **payload.model_dump(exclude_none=True),
    )
