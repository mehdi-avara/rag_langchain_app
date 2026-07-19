"""
Currency service functions.

These are the ONLY functions other modules should call to work with currencies.
No other module should import Currency or ExchangeRate models directly.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import Currency, ExchangeRate



EXCHANGE_RATE_DECIMAL_PLACES = 10


def quantize_decimal(
    value,
    decimal_places: int,
) -> Decimal:
    normalized_places = int(decimal_places)

    if not 0 <= normalized_places <= 10:
        raise ValueError(
            "decimal_places must be between 0 and 10"
        )

    quantum = Decimal("1").scaleb(
        -normalized_places
    )

    return Decimal(str(value)).quantize(
        quantum,
        rounding=ROUND_HALF_UP,
    )


def quantize_money(
    value,
    decimal_places: int,
) -> Decimal:
    return quantize_decimal(
        value,
        decimal_places,
    )


def quantize_exchange_rate(value) -> Decimal:
    return quantize_decimal(
        value,
        EXCHANGE_RATE_DECIMAL_PLACES,
    )


# ── Currency CRUD ─────────────────────────────────────────────────────────────

def list_currencies(db: Session, active_only: bool = True) -> List[Currency]:
    q = db.query(Currency)
    if active_only:
        q = q.filter(Currency.is_active == True)
    return q.order_by(Currency.code).all()


def get_currency_by_code(db: Session, code: str) -> Optional[Currency]:
    return db.query(Currency).filter(Currency.code == code.upper()).first()


def get_currency_or_404(db: Session, currency_id: int) -> Currency:
    c = db.query(Currency).filter(Currency.id == currency_id).first()
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Currency not found")
    return c


def create_currency(db: Session, code: str, name: str, symbol: Optional[str],
                    decimal_places: int, is_active: bool = True) -> Currency:
    existing = get_currency_by_code(db, code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Currency '{code}' already exists",
        )
    currency = Currency(
        code=code.upper(),
        name=name,
        symbol=symbol,
        decimal_places=decimal_places,
        is_active=is_active,
    )
    db.add(currency)
    db.commit()
    db.refresh(currency)
    return currency


def update_currency(db: Session, currency_id: int, **kwargs) -> Currency:
    c = get_currency_or_404(db, currency_id)
    for key, value in kwargs.items():
        if value is not None:
            setattr(c, key, value)
    db.commit()
    db.refresh(c)
    return c


# ── Exchange rate CRUD ────────────────────────────────────────────────────────

def list_exchange_rates(
    db: Session,
    from_currency_id: Optional[int] = None,
    to_currency_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
) -> List[ExchangeRate]:
    q = db.query(ExchangeRate)
    if from_currency_id:
        q = q.filter(ExchangeRate.from_currency_id == from_currency_id)
    if to_currency_id:
        q = q.filter(ExchangeRate.to_currency_id == to_currency_id)
    if date_from:
        q = q.filter(ExchangeRate.effective_date >= date_from)
    if date_to:
        q = q.filter(ExchangeRate.effective_date <= date_to)
    return q.order_by(ExchangeRate.effective_date.desc()).limit(limit).all()


def create_exchange_rate(
    db: Session,
    from_currency_id: int,
    to_currency_id: int,
    rate: Decimal,
    effective_date: date,
    source: str = "manual",
    created_by_user_id: Optional[int] = None,
) -> ExchangeRate:
    # Validate both currencies exist
    get_currency_or_404(db, from_currency_id)
    get_currency_or_404(db, to_currency_id)

    er = ExchangeRate(
        from_currency_id=from_currency_id,
        to_currency_id=to_currency_id,
        rate=rate,
        effective_date=effective_date,
        source=source,
        created_by_user_id=created_by_user_id,
    )
    db.add(er)
    db.commit()
    db.refresh(er)
    return er


# ── Core conversion logic ─────────────────────────────────────────────────────

def get_rate(
    db: Session,
    from_code: str,
    to_code: str,
    on_date: date,
) -> Optional[Decimal]:
    """
    Returns the exchange rate from from_code to to_code valid on on_date.
    Uses the closest rate with effective_date <= on_date.
    Returns None if no rate exists.

    Same-currency always returns 1.
    """
    if from_code.upper() == to_code.upper():
        return Decimal("1")

    from_c = get_currency_by_code(db, from_code)
    to_c = get_currency_by_code(db, to_code)

    if not from_c or not to_c:
        return None

    row = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency_id == from_c.id,
            ExchangeRate.to_currency_id == to_c.id,
            ExchangeRate.effective_date <= on_date,
        )
        .order_by(ExchangeRate.effective_date.desc())
        .first()
    )

    if row:
        return Decimal(str(row.rate))

    # Try inverse rate (1 / rate) as fallback
    inverse_row = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency_id == to_c.id,
            ExchangeRate.to_currency_id == from_c.id,
            ExchangeRate.effective_date <= on_date,
        )
        .order_by(ExchangeRate.effective_date.desc())
        .first()
    )

    if inverse_row:
        return Decimal("1") / Decimal(str(inverse_row.rate))

    return None


def convert(
    db: Session,
    amount: Decimal,
    from_code: str,
    to_code: str,
    on_date: date,
) -> Decimal:
    """
    Convert amount from from_code to to_code using rate on on_date.
    Raises HTTPException 422 if no rate is available.
    """
    rate = get_rate(db, from_code, to_code, on_date)
    if rate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No exchange rate found for {from_code} → {to_code} on or before {on_date}",
        )
    return amount * rate
