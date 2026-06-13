from __future__ import annotations

import enum
import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError


class PropertyCategory(str, enum.Enum):
    HOUSE = "house"
    CAR = "car"
    LAND = "land"
    OFFICE = "office"
    OTHER = "other"


HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_hex_color(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    if not HEX_COLOR_RE.fullmatch(normalized):
        raise PydanticCustomError("hex_color", "color must be a hex color in #RRGGBB format")

    return normalized.lower()




class WarehouseModelSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    manufacturer: str
    model: str
    type: Optional[str] = None


class WarehouseItemBase(BaseModel):
    model_id: int
    color: str = Field(..., min_length=1)
    count: int = Field(default=0, ge=0)
    description: Optional[str] = None
    unit_cost: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    unit_current_value: Optional[Decimal] = Field(default=None, ge=Decimal("0"))

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        return normalize_hex_color(value)


class WarehouseItemCreate(WarehouseItemBase):
    pass


class WarehouseItemUpdate(BaseModel):
    model_id: Optional[int] = None
    color: Optional[str] = Field(default=None, min_length=1)
    count: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = None
    unit_cost: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    unit_current_value: Optional[Decimal] = Field(default=None, ge=Decimal("0"))

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        return normalize_hex_color(value)



class WarehouseSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    model_type: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class WarehouseCountAdjustRequest(BaseModel):
    amount: int = Field(..., gt=0)


class WarehouseItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    owner_id: int
    model: WarehouseModelSummaryOut
    color: str
    count: int
    description: Optional[str] = None
    unit_cost: Optional[Decimal] = None
    unit_current_value: Optional[Decimal] = None
    total_cost: Decimal
    total_current_value: Decimal
    created_at: datetime
    updated_at: datetime


class OwnedPropertyBase(BaseModel):
    category: PropertyCategory
    title: str = Field(..., min_length=1)
    purchase_cost: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    current_estimated_value: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    description: Optional[str] = None


class OwnedPropertyCreate(OwnedPropertyBase):
    pass


class OwnedPropertyUpdate(BaseModel):
    category: Optional[PropertyCategory] = None
    title: Optional[str] = Field(default=None, min_length=1)
    purchase_cost: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    current_estimated_value: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
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
