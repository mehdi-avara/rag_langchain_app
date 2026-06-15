"""Pydantic schemas for Currency and ExchangeRate endpoints."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Currency schemas ──────────────────────────────────────────────────────────

class CurrencyCreate(BaseModel):
    code: str = Field(..., max_length=10, description="ISO 4217 code, e.g. USD")
    name: str = Field(..., max_length=100)
    symbol: Optional[str] = Field(None, max_length=10)
    decimal_places: int = Field(2, ge=0, le=10)
    is_active: bool = True


class CurrencyRead(BaseModel):
    id: int
    code: str
    name: str
    symbol: Optional[str]
    decimal_places: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CurrencyUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    symbol: Optional[str] = Field(None, max_length=10)
    decimal_places: Optional[int] = Field(None, ge=0, le=10)
    is_active: Optional[bool] = None


# ── ExchangeRate schemas ──────────────────────────────────────────────────────

class ExchangeRateCreate(BaseModel):
    from_currency_id: int
    to_currency_id: int
    rate: Decimal = Field(..., gt=0, description="Rate: 1 from_currency = rate to_currency")
    effective_date: date
    source: str = "manual"


class ExchangeRateRead(BaseModel):
    id: int
    from_currency_id: int
    to_currency_id: int
    from_currency_code: Optional[str] = None
    to_currency_code: Optional[str] = None
    rate: Decimal
    effective_date: date
    source: str
    created_by_user_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class ExchangeRateFilter(BaseModel):
    from_currency_id: Optional[int] = None
    to_currency_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


# ── Conversion utility response ───────────────────────────────────────────────

class ConvertResponse(BaseModel):
    amount: Decimal
    from_code: str
    to_code: str
    converted: Decimal
    rate_used: Decimal
    rate_date: date
