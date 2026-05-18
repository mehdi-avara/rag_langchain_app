from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import FinancialReceipt
from ..schemas import FinancialReceiptBatchRequest, FinancialReceiptCreate, FinancialReceiptOut, FinancialReceiptUpdate
from ..services import (
    get_card_or_404,
    get_customer_or_404,
    get_receipt_or_404,
    receipt_to_out,
    safe_embed_text,
)


router = APIRouter(prefix="/receipts")


def _resolve_counterparty_name(counterparty_name: Optional[str], customer_name: Optional[str]) -> str:
    normalized = (counterparty_name or "").strip()
    if normalized:
        return normalized

    customer_normalized = (customer_name or "").strip()
    if customer_normalized:
        return customer_normalized

    raise HTTPException(status_code=422, detail="counterparty_name is required when customer is not provided")


@router.post("", response_model=FinancialReceiptOut, status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: FinancialReceiptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:create")),
):
    card = get_card_or_404(db, payload.credit_card_id, current_user)
    customer = get_customer_or_404(db, payload.customer_id, current_user) if payload.customer_id is not None else None
    embedding = safe_embed_text(payload.description)
    counterparty_name = _resolve_counterparty_name(payload.counterparty_name, customer.name if customer else None)

    receipt = FinancialReceipt(
        company_id=current_user.company_id,
        owner_id=current_user.id,
        credit_card_id=card.id,
        customer_id=customer.id if customer else None,
        description=payload.description,
        description_embedding=embedding,
        tracking_number=payload.tracking_number,
        amount=payload.amount,
        direction=payload.direction,
        counterparty_name=counterparty_name,
        receipt_date=payload.receipt_date,
    )

    receipt.credit_card = card
    receipt.customer = customer

    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    return receipt_to_out(receipt)


@router.get("", response_model=List[FinancialReceiptOut])
def list_receipts(
    direction: Optional[str] = Query(None),
    credit_card_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None, description="Gregorian date, format YYYY-MM-DD"),
    date_to: Optional[date] = Query(None, description="Gregorian date, format YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:read")),
):
    query = (
        db.query(FinancialReceipt)
        .options(
            joinedload(FinancialReceipt.credit_card),
            joinedload(FinancialReceipt.customer),
            joinedload(FinancialReceipt.files),
        )
        .filter(FinancialReceipt.company_id == current_user.company_id)
    )

    if direction:
        query = query.filter(FinancialReceipt.direction == direction)

    if credit_card_id is not None:
        query = query.filter(FinancialReceipt.credit_card_id == credit_card_id)

    if date_from:
        query = query.filter(FinancialReceipt.receipt_date >= datetime.combine(date_from, time.min))

    if date_to:
        query = query.filter(FinancialReceipt.receipt_date <= datetime.combine(date_to, time.max))

    receipts = (
        query
        .order_by(FinancialReceipt.receipt_date.desc(), FinancialReceipt.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [receipt_to_out(receipt) for receipt in receipts]


@router.get("/{receipt_id}", response_model=FinancialReceiptOut)
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:read")),
):
    receipt = (
        db.query(FinancialReceipt)
        .options(
            joinedload(FinancialReceipt.credit_card),
            joinedload(FinancialReceipt.customer),
            joinedload(FinancialReceipt.files),
        )
        .filter(
            FinancialReceipt.id == receipt_id,
            FinancialReceipt.company_id == current_user.company_id,
        )
        .first()
    )

    if not receipt:
        raise HTTPException(status_code=404, detail="Financial receipt not found")

    return receipt_to_out(receipt)


@router.post("/batch", response_model=List[FinancialReceiptOut], status_code=status.HTTP_200_OK)
def get_receipts_by_ids(
    payload: FinancialReceiptBatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:read")),
):
    receipt_ids = list(dict.fromkeys(payload.ids))

    if not receipt_ids:
        return []

    receipts = (
        db.query(FinancialReceipt)
        .options(
            joinedload(FinancialReceipt.credit_card),
            joinedload(FinancialReceipt.customer),
            joinedload(FinancialReceipt.files),
        )
        .filter(
            FinancialReceipt.id.in_(receipt_ids),
            FinancialReceipt.company_id == current_user.company_id,
        )
        .all()
    )

    receipts_by_id = {receipt.id: receipt_to_out(receipt) for receipt in receipts}

    return [receipts_by_id[receipt_id] for receipt_id in receipt_ids if receipt_id in receipts_by_id]


@router.put("/{receipt_id}", response_model=FinancialReceiptOut)
def update_receipt(
    receipt_id: int,
    payload: FinancialReceiptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:update")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    customer = receipt.customer

    if "credit_card_id" in data and data["credit_card_id"] is not None:
        card = get_card_or_404(db, data["credit_card_id"], current_user)
        receipt.credit_card_id = card.id
        receipt.credit_card = card

    if "customer_id" in data:
        if data["customer_id"] is None:
            receipt.customer_id = None
            receipt.customer = None
            customer = None
        else:
            customer = get_customer_or_404(db, data["customer_id"], current_user)
            receipt.customer_id = customer.id
            receipt.customer = customer

    if "receipt_date" in data and data["receipt_date"] is not None:
        receipt.receipt_date = data.pop("receipt_date")

    if "description" in data and data["description"] is not None:
        receipt.description_embedding = safe_embed_text(data["description"])

    if "counterparty_name" in data or "customer_id" in data:
        data["counterparty_name"] = _resolve_counterparty_name(
            data.get("counterparty_name", receipt.counterparty_name),
            customer.name if customer else None,
        )

    for key, value in data.items():
        if key in {"credit_card_id", "customer_id"}:
            continue
        setattr(receipt, key, value)

    db.commit()
    db.refresh(receipt)

    return receipt_to_out(receipt)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:delete")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)

    db.delete(receipt)
    db.commit()

    return None
