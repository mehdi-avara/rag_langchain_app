from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..purchase_cost_allocation_service import (
    create_purchase_cost_allocations,
    delete_purchase_cost_allocation,
    list_purchase_cost_allocations,
)
from ..schemas import (
    PurchaseCostPaymentAllocationCreate,
    PurchaseCostPaymentAllocationRead,
)


router = APIRouter(
    prefix="/receipts",
    tags=["financial_management"],
)


@router.get(
    (
        "/{receipt_id}/"
        "purchase-cost-allocations"
    ),
    response_model=list[
        PurchaseCostPaymentAllocationRead
    ],
)
def list_allocations(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            (
                "financial_management:"
                "purchase_cost_allocations:"
                "read"
            )
        )
    ),
):
    return list_purchase_cost_allocations(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
    )


@router.post(
    (
        "/{receipt_id}/"
        "purchase-cost-allocations"
    ),
    response_model=list[
        PurchaseCostPaymentAllocationRead
    ],
    status_code=status.HTTP_201_CREATED,
)
def create_allocations(
    receipt_id: int,
    payload: list[
        PurchaseCostPaymentAllocationCreate
    ],
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            (
                "financial_management:"
                "purchase_cost_allocations:"
                "create"
            )
        )
    ),
):
    return create_purchase_cost_allocations(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
        allocations=payload,
    )


@router.delete(
    (
        "/{receipt_id}/"
        "purchase-cost-allocations/"
        "{allocation_id}"
    ),
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_allocation(
    receipt_id: int,
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            (
                "financial_management:"
                "purchase_cost_allocations:"
                "delete"
            )
        )
    ),
):
    delete_purchase_cost_allocation(
        db=db,
        current_user=current_user,
        receipt_id=receipt_id,
        allocation_id=allocation_id,
    )

    return None
