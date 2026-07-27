from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import FinancialReceipt
from ..purchase_cost_allocation_service import (
    assert_receipt_delete_allowed,
    assert_receipt_financial_edit_allowed,
    create_purchase_cost_allocations,
)
from ..schemas import FinancialReceiptBatchRequest, FinancialReceiptCreate, FinancialReceiptCurrencySummaryOut, FinancialReceiptOut, FinancialReceiptSummaryOut, FinancialReceiptUpdate
from ..services import (
    calculate_receipt_currency_fields,
    get_card_or_404,
    get_customer_or_404,
    get_receipt_or_404,
    receipt_to_out,
    resolve_receipt_money_fields,
    safe_embed_text,
    summarize_receipts,
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


@router.post(
    "",
    response_model=FinancialReceiptOut,
    status_code=status.HTTP_201_CREATED,
)
def create_receipt(
    payload: FinancialReceiptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "financial_management:receipts:create"
        )
    ),
):
    card = get_card_or_404(
        db,
        payload.credit_card_id,
        current_user,
    )

    customer = (
        get_customer_or_404(
            db,
            payload.customer_id,
            current_user,
        )
        if payload.customer_id is not None
        else None
    )

    embedding = safe_embed_text(
        payload.description
    )

    counterparty_name = (
        _resolve_counterparty_name(
            payload.counterparty_name,
            customer.name
            if customer
            else None,
        )
    )

    supplied_fields = set(
        payload.model_fields_set
    )

    supplied_rate = None

    if "exchange_rate_used" in supplied_fields:
        supplied_rate = (
            payload.exchange_rate_used
        )
    elif (
        "exchange_rate_to_base"
        in supplied_fields
    ):
        supplied_rate = (
            payload.exchange_rate_to_base
        )

    currency_code = (
        payload.currency
        if "currency" in supplied_fields
        else None
    )

    money_fields = (
        resolve_receipt_money_fields(
            db=db,
            current_user=current_user,
            amount=payload.amount,
            receipt_date=(
                payload.receipt_date
            ),
            currency_id=(
                payload.currency_id
            ),
            exchange_rate_used=(
                supplied_rate
            ),
            currency_code=currency_code,
        )
    )

    receipt = FinancialReceipt(
        company_id=current_user.company_id,
        owner_id=current_user.id,
        credit_card_id=card.id,
        customer_id=(
            customer.id
            if customer
            else None
        ),
        description=payload.description,
        description_embedding=embedding,
        tracking_number=(
            payload.tracking_number
        ),
        direction=payload.direction,
        counterparty_name=(
            counterparty_name
        ),
        receipt_date=payload.receipt_date,
        **money_fields,
    )

    receipt.credit_card = card
    receipt.customer = customer

    try:
        db.add(receipt)

        allocations = (
            payload.purchase_cost_allocations
            or []
        )

        if allocations:
            db.flush()

            create_purchase_cost_allocations(
                db=db,
                current_user=current_user,
                receipt_id=receipt.id,
                allocations=allocations,
                commit=False,
            )

        db.commit()
        db.refresh(receipt)

    except Exception:
        db.rollback()
        raise

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
    current_user: User = Depends(require_permission("financial_management:receipts:read")),
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



@router.get("/summary", response_model=FinancialReceiptSummaryOut)
def get_receipts_summary(
    direction: Optional[str] = Query(None),
    credit_card_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None, description="Gregorian date, format YYYY-MM-DD"),
    date_to: Optional[date] = Query(None, description="Gregorian date, format YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipts:read")),
):
    return summarize_receipts(
        db,
        current_user,
        direction=direction,
        credit_card_id=credit_card_id,
        date_from=date_from,
        date_to=date_to,
    )

@router.get("/{receipt_id}", response_model=FinancialReceiptOut)
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipts:read")),
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
    current_user: User = Depends(require_permission("financial_management:receipts:read")),
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


@router.put(
    "/{receipt_id}",
    response_model=FinancialReceiptOut,
)
def update_receipt(
    receipt_id: int,
    payload: FinancialReceiptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "financial_management:receipts:update"
        )
    ),
):
    receipt = get_receipt_or_404(
        db,
        receipt_id,
        current_user,
    )

    data = payload.model_dump(
        exclude_unset=True
    )

    changed_fields = set(data)

    assert_receipt_financial_edit_allowed(
        db=db,
        receipt=receipt,
        changed_fields=changed_fields,
    )

    customer = receipt.customer

    if (
        "credit_card_id" in data
        and data["credit_card_id"]
        is not None
    ):
        card = get_card_or_404(
            db,
            data.pop("credit_card_id"),
            current_user,
        )

        receipt.credit_card_id = card.id
        receipt.credit_card = card

    if "customer_id" in data:
        customer_id = data.pop(
            "customer_id"
        )

        if customer_id is None:
            receipt.customer_id = None
            receipt.customer = None
            customer = None
        else:
            customer = get_customer_or_404(
                db,
                customer_id,
                current_user,
            )

            receipt.customer_id = (
                customer.id
            )
            receipt.customer = customer

    money_keys = {
        "amount",
        "currency",
        "exchange_rate_to_base",
        "currency_id",
        "exchange_rate_used",
        "receipt_date",
    }

    if changed_fields & money_keys:
        new_amount = data.pop(
            "amount",
            receipt.amount,
        )

        new_receipt_date = data.pop(
            "receipt_date",
            receipt.receipt_date,
        )

        if new_receipt_date is None:
            new_receipt_date = (
                receipt.receipt_date
            )

        canonical_currency_supplied = (
            "currency_id"
            in changed_fields
        )

        legacy_currency_supplied = (
            "currency"
            in changed_fields
        )

        if canonical_currency_supplied:
            new_currency_id = data.pop(
                "currency_id",
                None,
            )
        elif legacy_currency_supplied:
            new_currency_id = None
        else:
            new_currency_id = (
                receipt.currency_id
            )

        new_currency_code = (
            data.pop(
                "currency",
                None,
            )
            if legacy_currency_supplied
            else None
        )

        if (
            "exchange_rate_used"
            in changed_fields
        ):
            new_rate = data.pop(
                "exchange_rate_used",
                None,
            )
            data.pop(
                "exchange_rate_to_base",
                None,
            )

        elif (
            "exchange_rate_to_base"
            in changed_fields
        ):
            new_rate = data.pop(
                "exchange_rate_to_base",
                None,
            )
            data.pop(
                "exchange_rate_used",
                None,
            )

        elif (
            canonical_currency_supplied
            or legacy_currency_supplied
            or "receipt_date"
            in changed_fields
        ):
            new_rate = None

        else:
            new_rate = (
                receipt.exchange_rate_used
            )

        money_fields = (
            resolve_receipt_money_fields(
                db=db,
                current_user=current_user,
                amount=new_amount,
                receipt_date=(
                    new_receipt_date
                ),
                currency_id=(
                    new_currency_id
                ),
                exchange_rate_used=(
                    new_rate
                ),
                currency_code=(
                    new_currency_code
                ),
            )
        )

        for key, value in (
            money_fields.items()
        ):
            setattr(
                receipt,
                key,
                value,
            )

        receipt.receipt_date = (
            new_receipt_date
        )

    if (
        "description" in data
        and data["description"]
        is not None
    ):
        receipt.description_embedding = (
            safe_embed_text(
                data["description"]
            )
        )

    if (
        "counterparty_name"
        in data
        or "customer_id"
        in changed_fields
    ):
        data["counterparty_name"] = (
            _resolve_counterparty_name(
                data.get(
                    "counterparty_name",
                    receipt.counterparty_name,
                ),
                customer.name
                if customer
                else None,
            )
        )

    ignored_fields = {
        "credit_card_id",
        "customer_id",
        "amount",
        "currency",
        "exchange_rate_to_base",
        "currency_id",
        "exchange_rate_used",
        "receipt_date",
    }

    for key, value in data.items():
        if key in ignored_fields:
            continue

        setattr(
            receipt,
            key,
            value,
        )

    try:
        db.commit()
        db.refresh(receipt)

    except Exception:
        db.rollback()
        raise

    return receipt_to_out(receipt)



@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipts:delete")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)

    assert_receipt_delete_allowed(
        db=db,
        receipt=receipt,
    )

    db.delete(receipt)
    db.commit()

    return None
