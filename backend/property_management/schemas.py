from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


PROPERTY_AMOUNT_MAX_DIGITS = 24
PROPERTY_AMOUNT_DECIMAL_PLACES = 2


class PropertyCategory(str, enum.Enum):
    HOUSE = "house"
    CAR = "car"
    LAND = "land"
    OFFICE = "office"
    OTHER = "other"


class OwnedPropertyBase(BaseModel):
    category: PropertyCategory
    title: str = Field(..., min_length=1)
    purchase_cost: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=PROPERTY_AMOUNT_MAX_DIGITS,
        decimal_places=PROPERTY_AMOUNT_DECIMAL_PLACES,
    )
    current_estimated_value: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=PROPERTY_AMOUNT_MAX_DIGITS,
        decimal_places=PROPERTY_AMOUNT_DECIMAL_PLACES,
    )
    description: Optional[str] = None


class OwnedPropertyCreate(OwnedPropertyBase):
    pass


class OwnedPropertyUpdate(BaseModel):
    category: Optional[PropertyCategory] = None
    title: Optional[str] = Field(default=None, min_length=1)
    purchase_cost: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=PROPERTY_AMOUNT_MAX_DIGITS,
        decimal_places=PROPERTY_AMOUNT_DECIMAL_PLACES,
    )
    current_estimated_value: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=PROPERTY_AMOUNT_MAX_DIGITS,
        decimal_places=PROPERTY_AMOUNT_DECIMAL_PLACES,
    )
    description: Optional[str] = None


class OwnedPropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    owner_id: int
    category: PropertyCategory
    title: str
    purchase_cost: Optional[Decimal] = None
    current_estimated_value: Optional[Decimal] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NetWorthSummaryOut(BaseModel):
    warehouse_cost_total: Decimal
    warehouse_current_value_total: Decimal
    property_cost_total: Decimal
    property_current_value_total: Decimal
    cash_balance: Decimal
    net_worth: Decimal
