from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..models import BuyingProcessItem
from ..schemas import BuyingProcessItemCreate, BuyingProcessItemOut, BuyingProcessItemUpdate
from ..services import (
    compute_item_amounts,
    ensure_process_editable,
    get_buying_item_or_404,
    get_buying_process_or_404,
    get_model_for_company_or_404,
)


router = APIRouter(prefix="/processes/{process_id}/items")


@router.post("", response_model=BuyingProcessItemOut, status_code=status.HTTP_201_CREATED)
def create_buying_item(
    process_id: int,
    payload: BuyingProcessItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    get_model_for_company_or_404(db, payload.model_id, process.company_id)

    item = BuyingProcessItem(
        buying_process_id=process.id,
        model_id=payload.model_id,
        color=payload.color,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        currency=payload.currency or process.currency,
        exchange_rate_to_base=payload.exchange_rate_to_base or process.exchange_rate_to_base,
        allocated_cost_base=0,
        final_unit_cost_base=0,
    )
    compute_item_amounts(item)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=BuyingProcessItemOut)
def update_buying_item(
    process_id: int,
    item_id: int,
    payload: BuyingProcessItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    item = get_buying_item_or_404(db, process, item_id)
    data = payload.model_dump(exclude_unset=True)

    if "model_id" in data and data["model_id"] is not None:
        get_model_for_company_or_404(db, data["model_id"], process.company_id)

    for key, value in data.items():
        if value is None:
            continue
        setattr(item, key, value)

    compute_item_amounts(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buying_item(
    process_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    item = get_buying_item_or_404(db, process, item_id)
    db.delete(item)
    db.commit()
    return None
