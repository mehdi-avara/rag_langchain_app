"""Additional cost routes."""
from __future__ import annotations

from typing import List

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import (
    PurchaseOrderCostCreate,
    PurchaseOrderCostRead,
    PurchaseOrderCostUpdate,
)
from ..services import (
    add_cost,
    delete_cost,
    update_cost,
)

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



@router.patch(
    "/purchase/orders/{po_id}/costs/{cost_id}",
    response_model=PurchaseOrderCostRead,
)
def patch_cost(
    po_id: int,
    cost_id: int,
    payload: PurchaseOrderCostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:costs:manage"
        )
    ),
):
    return update_cost(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_id=cost_id,
        data=payload.model_dump(
            exclude_unset=True
        ),
    )


@router.delete(
    "/purchase/orders/{po_id}/costs/{cost_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_cost(
    po_id: int,
    cost_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:costs:manage"
        )
    ),
):
    delete_cost(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_id=cost_id,
    )
