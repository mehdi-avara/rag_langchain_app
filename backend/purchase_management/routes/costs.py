"""Purchase-order cost routes."""
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

from ..schemas import (
    PurchaseOrderCostConfirmActual,
    PurchaseOrderCostCreate,
    PurchaseOrderCostRead,
    PurchaseOrderCostUpdate,
    PurchaseOrderPaymentSummaryRead,
)
from ..services import (
    add_cost,
    confirm_purchase_order_cost_actual,
    delete_cost,
    get_purchase_order_cost,
    get_purchase_order_payment_summary,
    list_purchase_order_costs,
    update_cost,
)


router = APIRouter(
    tags=["purchase_management"]
)


@router.get(
    "/purchase/orders/{po_id}/costs",
    response_model=list[
        PurchaseOrderCostRead
    ],
)
def list_costs(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:costs:read"
        )
    ),
):
    return list_purchase_order_costs(
        db=db,
        user=current_user,
        po_id=po_id,
    )


@router.get(
    "/purchase/orders/{po_id}/payment-summary",
    response_model=PurchaseOrderPaymentSummaryRead,
)
def get_payment_summary(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            (
                "purchase_management:"
                "payment_summary:read"
            )
        )
    ),
):
    return get_purchase_order_payment_summary(
        db=db,
        user=current_user,
        po_id=po_id,
    )


@router.post(
    "/purchase/orders/{po_id}/costs",
    response_model=PurchaseOrderCostRead,
    status_code=status.HTTP_201_CREATED,
)
def create_cost(
    po_id: int,
    payload: PurchaseOrderCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:costs:manage"
        )
    ),
):
    return add_cost(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_type=payload.cost_type,
        description=payload.description,
        predicted_amount=(
            payload.predicted_amount
        ),
        predicted_currency_id=(
            payload.predicted_currency_id
        ),
    )


@router.post(
    (
        "/purchase/orders/{po_id}/costs/"
        "{cost_id}/confirm-actual"
    ),
    response_model=PurchaseOrderCostRead,
)
def confirm_actual_cost(
    po_id: int,
    cost_id: int,
    payload: PurchaseOrderCostConfirmActual,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            (
                "purchase_management:"
                "costs:confirm_actual"
            )
        )
    ),
):
    return confirm_purchase_order_cost_actual(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_id=cost_id,
        amount=payload.amount,
        currency_id=payload.currency_id,
    )


@router.get(
    (
        "/purchase/orders/{po_id}/costs/"
        "{cost_id}"
    ),
    response_model=PurchaseOrderCostRead,
)
def get_cost(
    po_id: int,
    cost_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:costs:read"
        )
    ),
):
    return get_purchase_order_cost(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_id=cost_id,
    )


@router.patch(
    (
        "/purchase/orders/{po_id}/costs/"
        "{cost_id}"
    ),
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
    data = payload.model_dump(
        exclude_unset=True
    )

    if (
        "predicted_amount" not in data
        and "amount" in data
    ):
        data["predicted_amount"] = (
            data["amount"]
        )

    if (
        "predicted_currency_id"
        not in data
        and "currency_id" in data
    ):
        data["predicted_currency_id"] = (
            data["currency_id"]
        )

    data.pop("amount", None)
    data.pop("currency_id", None)
    data.pop("allocation_method", None)

    return update_cost(
        db=db,
        user=current_user,
        po_id=po_id,
        cost_id=cost_id,
        data=data,
    )


@router.delete(
    (
        "/purchase/orders/{po_id}/costs/"
        "{cost_id}"
    ),
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

    return None
