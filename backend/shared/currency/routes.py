"""HTTP routes for the currency shared module.

Registered under prefix /currencies in api.py.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User

from .schemas import (
    CurrencyCreate,
    CurrencyRead,
    CurrencyUpdate,
    ExchangeRateCreate,
    ExchangeRateRead,
    ConvertResponse,
)
from .services import (
    convert,
    create_currency,
    create_exchange_rate,
    get_currency_or_404,
    get_rate,
    list_currencies,
    list_exchange_rates,
    update_currency,
)

router = APIRouter()


# ── Currency endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=List[CurrencyRead], summary="List active currencies")
def get_currencies(
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("currencies:read")),
):
    return list_currencies(db, active_only=active_only)


@router.post("", response_model=CurrencyRead, status_code=201, summary="Create a currency (admin only)")
def post_currency(
    payload: CurrencyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("currencies:create")),
):
    return create_currency(
        db,
        code=payload.code,
        name=payload.name,
        symbol=payload.symbol,
        decimal_places=payload.decimal_places,
        is_active=payload.is_active,
    )


# ── Exchange rate endpoints ───────────────────────────────────────────────────

@router.get("/exchange-rates", response_model=List[ExchangeRateRead], summary="List exchange rates")
def get_exchange_rates(
    from_currency_id: Optional[int] = Query(None),
    to_currency_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exchange_rates:read")),
):
    rows = list_exchange_rates(
        db,
        from_currency_id=from_currency_id,
        to_currency_id=to_currency_id,
        date_from=date_from,
        date_to=date_to,
    )
    results = []
    for r in rows:
        results.append(ExchangeRateRead(
            id=r.id,
            from_currency_id=r.from_currency_id,
            to_currency_id=r.to_currency_id,
            from_currency_code=r.from_currency.code if r.from_currency else None,
            to_currency_code=r.to_currency.code if r.to_currency else None,
            rate=Decimal(str(r.rate)),
            effective_date=r.effective_date,
            source=r.source,
            created_by_user_id=r.created_by_user_id,
            created_at=r.created_at,
        ))
    return results


@router.post("/exchange-rates", response_model=ExchangeRateRead, status_code=201, summary="Add exchange rate")
def post_exchange_rate(
    payload: ExchangeRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("exchange_rates:create")),
):
    er = create_exchange_rate(
        db,
        from_currency_id=payload.from_currency_id,
        to_currency_id=payload.to_currency_id,
        rate=payload.rate,
        effective_date=payload.effective_date,
        source=payload.source,
        created_by_user_id=current_user.id,
    )
    return ExchangeRateRead(
        id=er.id,
        from_currency_id=er.from_currency_id,
        to_currency_id=er.to_currency_id,
        from_currency_code=er.from_currency.code if er.from_currency else None,
        to_currency_code=er.to_currency.code if er.to_currency else None,
        rate=Decimal(str(er.rate)),
        effective_date=er.effective_date,
        source=er.source,
        created_by_user_id=er.created_by_user_id,
        created_at=er.created_at,
    )


@router.get("/convert", response_model=ConvertResponse, summary="Convert amount between currencies")
def convert_amount(
    amount: Decimal = Query(..., gt=0),
    from_code: str = Query(...),
    to_code: str = Query(...),
    on_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("currencies:read")),
):
    rate = get_rate(db, from_code, to_code, on_date)
    converted = convert(db, amount, from_code, to_code, on_date)
    return ConvertResponse(
        amount=amount,
        from_code=from_code.upper(),
        to_code=to_code.upper(),
        converted=converted,
        rate_used=rate,
        rate_date=on_date,
    )


@router.get("/{currency_id}", response_model=CurrencyRead, summary="Get currency by ID")
def get_currency(
    currency_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("currencies:read")),
):
    return get_currency_or_404(db, currency_id)


@router.patch("/{currency_id}", response_model=CurrencyRead, summary="Update a currency")
def patch_currency(
    currency_id: int,
    payload: CurrencyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("currencies:manage")),
):
    return update_currency(db, currency_id, **payload.model_dump(exclude_none=True))
