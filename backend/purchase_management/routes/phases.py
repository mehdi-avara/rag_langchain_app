"""Delivery phase read and schedule-update routes."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..schemas import (
    PurchasePhaseRead,
    PurchasePhaseUpdate,
)
from ..services import (
    list_phases,
    update_phase,
)


router = APIRouter(
    tags=["purchase_management"]
)


@router.get(
    "/purchase/orders/{po_id}/phases",
    response_model=List[PurchasePhaseRead],
)
def get_phases(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:orders:read"
        )
    ),
):
    return list_phases(
        db,
        current_user,
        po_id,
    )


@router.patch(
    "/purchase/orders/{po_id}/phases/{phase_id}",
    response_model=PurchasePhaseRead,
)
def patch_phase(
    po_id: int,
    phase_id: int,
    payload: PurchasePhaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "purchase_management:phases:manage"
        )
    ),
):
    allowed = {
        "title",
        "description",
        "expected_delivery_date",
    }
    values = {
        key: value
        for key, value in payload.model_dump(
            exclude_unset=True
        ).items()
        if key in allowed
    }

    return update_phase(
        db,
        current_user,
        po_id,
        phase_id,
        **values,
    )
