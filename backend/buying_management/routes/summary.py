from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission

from ..models import BuyingProcessStatus
from ..schemas import BuyingProcessOut, BuyingProcessSummaryOut
from ..services import apply_buying_to_warehouse, calculate_buying_summary, get_buying_process_or_404


router = APIRouter(prefix="/processes/{process_id}")


@router.get("/summary", response_model=BuyingProcessSummaryOut)
def get_buying_summary(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:summary")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    summary = calculate_buying_summary(db, process)
    db.commit()
    return summary


@router.post("/apply-warehouse", response_model=BuyingProcessSummaryOut)
def apply_warehouse(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:apply_warehouse")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    return apply_buying_to_warehouse(db, process, current_user)


@router.post("/close", response_model=BuyingProcessOut)
def close_buying_process(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    if not process.items:
        raise HTTPException(status_code=409, detail="Cannot close a buying process with no items")
    process.status = BuyingProcessStatus.CLOSED.value
    db.commit()
    db.refresh(process)
    return process


@router.post("/cancel", response_model=BuyingProcessOut)
def cancel_buying_process(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("buying_management:update")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    if process.warehouse_applied_at is not None:
        raise HTTPException(status_code=409, detail="Cannot cancel after warehouse was applied")
    process.status = BuyingProcessStatus.CANCELLED.value
    db.commit()
    db.refresh(process)
    return process

