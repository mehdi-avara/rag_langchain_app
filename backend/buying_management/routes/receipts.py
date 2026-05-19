from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permissions

from ..models import BuyingProcessReceiptLink
from ..schemas import BuyingProcessReceiptLinkCreate, BuyingProcessReceiptLinkOut
from ..services import (
    ensure_process_editable,
    get_buying_process_or_404,
    get_receipt_for_company_or_404,
    receipt_link_exists,
)


router = APIRouter(prefix="/processes/{process_id}/receipts")


@router.post("", response_model=BuyingProcessReceiptLinkOut, status_code=status.HTTP_201_CREATED)
def create_buying_receipt_link(
    process_id: int,
    payload: BuyingProcessReceiptLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("buying_management:update", "financial_management:read")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    get_receipt_for_company_or_404(db, payload.receipt_id, process.company_id)
    if receipt_link_exists(db, process.id, payload.receipt_id):
        raise HTTPException(status_code=409, detail="Receipt already linked to buying process")

    link = BuyingProcessReceiptLink(
        buying_process_id=process.id,
        receipt_id=payload.receipt_id,
        linked_by_user_id=current_user.id,
        purpose=payload.purpose.value,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("", response_model=List[BuyingProcessReceiptLinkOut])
def list_buying_receipt_links(
    process_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("buying_management:read", "financial_management:read")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    return (
        db.query(BuyingProcessReceiptLink)
        .filter(BuyingProcessReceiptLink.buying_process_id == process.id)
        .order_by(BuyingProcessReceiptLink.created_at.desc())
        .all()
    )


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buying_receipt_link(
    process_id: int,
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("buying_management:update", "financial_management:read")),
):
    process = get_buying_process_or_404(db, process_id, current_user)
    ensure_process_editable(process)
    link = (
        db.query(BuyingProcessReceiptLink)
        .filter(
            BuyingProcessReceiptLink.buying_process_id == process.id,
            BuyingProcessReceiptLink.receipt_id == receipt_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Receipt link not found")

    db.delete(link)
    db.commit()
    return None
