"""Phase CRUD routes."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..schemas import PurchasePhaseCreate, PurchasePhaseRead, PurchasePhaseUpdate
from ..services import add_phase, list_phases, update_phase

router = APIRouter(tags=["purchase_management"])


@router.get("/purchase/orders/{po_id}/phases", response_model=List[PurchasePhaseRead])
def get_phases(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:orders:read")),
):
    return list_phases(db, current_user, po_id)


@router.post("/purchase/orders/{po_id}/phases", response_model=PurchasePhaseRead, status_code=201)
def create_phase(
    po_id: int,
    payload: PurchasePhaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:phases:manage")),
):
    return add_phase(
        db, current_user, po_id,
        title=payload.title,
        description=payload.description,
        currency_id=payload.currency_id,
        exchange_rate_used=payload.exchange_rate_used,
        expected_delivery_date=payload.expected_delivery_date,
    )


@router.patch("/purchase/orders/{po_id}/phases/{phase_id}", response_model=PurchasePhaseRead)
def patch_phase(
    po_id: int,
    phase_id: int,
    payload: PurchasePhaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_management:phases:manage")),
):
    return update_phase(db, current_user, po_id, phase_id, **payload.model_dump(exclude_none=True))
