from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..models import BuyingCostAllocationMethod, BuyingProcessCost
from ..schemas import BuyingProcessCostCreate, BuyingProcessCostOut, BuyingProcessCostUpdate
from ..services import (
    compute_cost_amount,
    ensure_process_editable,
    get_buying_cost_or_404,
    get_buying_process_or_404,
    get_receipt_for_company_or_404,
    normalize_manual_allocations,
    validate_manual_allocation,
)


router = APIRouter(prefix="/processes/{process_id}/costs")


@router.post("", response_model=BuyingProcessCostOut, status_code=status.HTTP_201_CREATED)
def create_buying_cost(
    process_id: int,
    payload: BuyingProcessCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    if payload.receipt_id is not None:
        get_receipt_for_company_or_404(db, payload.receipt_id, process.company_id)

    cost = BuyingProcessCost(
        buying_process_id=process.id,
        receipt_id=payload.receipt_id,
        cost_type=payload.cost_type.value,
        amount=payload.amount,
        currency=payload.currency or process.currency,
        exchange_rate_to_base=payload.exchange_rate_to_base or process.exchange_rate_to_base,
        allocation_method=payload.allocation_method.value,
        manual_allocations_json=normalize_manual_allocations(payload.manual_allocations_json),
        description=payload.description,
    )
    compute_cost_amount(cost)
    if cost.allocation_method == BuyingCostAllocationMethod.MANUAL.value:
        validate_manual_allocation(cost, process.items)

    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


@router.put("/{cost_id}", response_model=BuyingProcessCostOut)
def update_buying_cost(
    process_id: int,
    cost_id: int,
    payload: BuyingProcessCostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    cost = get_buying_cost_or_404(db, process, cost_id)
    data = payload.model_dump(exclude_unset=True)

    if "receipt_id" in data and data["receipt_id"] is not None:
        get_receipt_for_company_or_404(db, data["receipt_id"], process.company_id)

    nullable_fields = {"receipt_id", "manual_allocations_json", "description"}
    for key, value in data.items():
        if value is None and key not in nullable_fields:
            continue
        if key in {"cost_type", "allocation_method"} and value is not None:
            value = value.value
        if key == "manual_allocations_json":
            value = normalize_manual_allocations(value)
        setattr(cost, key, value)

    compute_cost_amount(cost)
    if cost.allocation_method == BuyingCostAllocationMethod.MANUAL.value:
        validate_manual_allocation(cost, process.items)

    db.commit()
    db.refresh(cost)
    return cost


@router.delete("/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buying_cost(
    process_id: int,
    cost_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    cost = get_buying_cost_or_404(db, process, cost_id)
    db.delete(cost)
    db.commit()
    return None
