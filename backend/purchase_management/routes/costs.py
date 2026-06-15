"""Additional cost routes."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import PurchaseOrderCostCreate, PurchaseOrderCostRead
from ..services import add_cost

router = APIRouter(tags=["purchase_management"])


@router.post(
    "/purchase/orders/{po_id}/costs",
    response_model=PurchaseOrderCostRead,
    status_code=201,
)
def create_cost(
    po_id: int,
    payload: PurchaseOrderCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:costs:manage")),
):
    return add_cost(
        db, current_user, po_id,
        cost_type=payload.cost_type,
        description=payload.description,
        amount=payload.amount,
        currency_id=payload.currency_id,
        amount_base=payload.amount_base,
        base_currency_id=payload.base_currency_id,
        exchange_rate_used=payload.exchange_rate_used,
        allocation_method=payload.allocation_method,
    )
