from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    StockCountStatus,
    StockMovementType,
    StockReferenceType,
    WarehouseType,
)


def clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class WarehouseCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    warehouse_type: WarehouseType = WarehouseType.MAIN
    location: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    manager_id: Optional[int] = Field(None, gt=0)
    is_active: bool = True
    is_default: bool = False

    @field_validator("code", "name", "location", "address", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            raise ValueError("code is required")
        return value.upper()


class WarehouseUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    warehouse_type: Optional[WarehouseType] = None
    location: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    manager_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None

    @field_validator("code", "name", "location", "address", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return value.upper() if value else value


class WarehouseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    name: str
    warehouse_type: WarehouseType
    location: Optional[str]
    address: Optional[str]
    manager_id: Optional[int]
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ZoneCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

    @field_validator("code", "name", "description", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            raise ValueError("code is required")
        return value.upper()


class ZoneUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None

    @field_validator("code", "name", "description", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return value.upper() if value else value


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    code: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class StorageLocationCreate(BaseModel):
    zone_id: int = Field(..., gt=0)
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    capacity_unit: Optional[str] = Field(None, max_length=30)
    capacity_value: Optional[Decimal] = Field(None, ge=0)
    is_active: bool = True
    is_receiving: bool = False

    @field_validator("code", "name", "capacity_unit", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            raise ValueError("code is required")
        return value.upper()


class StorageLocationUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    capacity_unit: Optional[str] = Field(None, max_length=30)
    capacity_value: Optional[Decimal] = Field(None, ge=0)
    is_active: Optional[bool] = None
    is_receiving: Optional[bool] = None

    @field_validator("code", "name", "capacity_unit", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return value.upper() if value else value


class StorageLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zone_id: int
    code: str
    name: str
    capacity_unit: Optional[str]
    capacity_value: Optional[Decimal]
    is_active: bool
    is_receiving: bool
    created_at: datetime
    updated_at: datetime


class StockThresholdUpdate(BaseModel):
    min_level: Optional[Decimal] = Field(None, ge=0)
    max_level: Optional[Decimal] = Field(None, ge=0)
    reorder_point: Optional[Decimal] = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if (
            self.min_level is not None
            and self.max_level is not None
            and self.min_level > self.max_level
        ):
            raise ValueError("min_level cannot exceed max_level")

        return self


class StockItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    item_id: int
    storage_location_id: int
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    quantity_available: Decimal
    min_level: Optional[Decimal]
    max_level: Optional[Decimal]
    reorder_point: Optional[Decimal]
    unit_cost: Decimal
    unit_cost_currency_id: int
    unit_cost_base: Decimal
    created_at: datetime
    updated_at: datetime


class StockMovementCreate(BaseModel):
    movement_type: StockMovementType
    item_id: int = Field(..., gt=0)
    from_location_id: Optional[int] = Field(None, gt=0)
    to_location_id: Optional[int] = Field(None, gt=0)
    quantity: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)
    unit_cost_base: Decimal = Field(..., ge=0)
    base_currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(..., gt=0)
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)

    @model_validator(mode="after")
    def validate_locations(self):
        if self.from_location_id and self.to_location_id:
            if self.from_location_id == self.to_location_id:
                raise ValueError("from_location_id and to_location_id must differ")

        if self.movement_type in {
            StockMovementType.RECEIPT,
            StockMovementType.RETURN,
            StockMovementType.TRANSFER_IN,
        } and self.to_location_id is None:
            raise ValueError("to_location_id is required for this movement")

        if self.movement_type in {
            StockMovementType.ISSUE,
            StockMovementType.TRANSFER_OUT,
        } and self.from_location_id is None:
            raise ValueError("from_location_id is required for this movement")

        if self.movement_type == StockMovementType.TRANSFER_OUT:
            if self.to_location_id is None:
                raise ValueError("to_location_id is required for transfer_out")

        if self.movement_type in {
            StockMovementType.ADJUSTMENT,
            StockMovementType.COUNT_ADJUSTMENT,
        }:
            if self.from_location_id is None and self.to_location_id is None:
                raise ValueError("an adjustment requires from_location_id or to_location_id")

        return self


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    movement_number: str
    movement_type: StockMovementType
    item_id: int
    from_location_id: Optional[int]
    to_location_id: Optional[int]
    quantity: Decimal
    unit_cost: Decimal
    currency_id: int
    unit_cost_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    reference_type: StockReferenceType
    reference_id: int
    reference_line_id: Optional[int]
    performed_by_user_id: Optional[int]
    movement_date: datetime
    notes: Optional[str]
    created_at: datetime


class StockItemSearchRead(BaseModel):
    id: int
    company_id: int
    item_id: int
    item_code: str
    item_name: str
    unit_code: str
    storage_location_id: int
    storage_location_code: str
    storage_location_name: str
    zone_id: int
    zone_code: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    quantity_available: Decimal
    min_level: Optional[Decimal]
    max_level: Optional[Decimal]
    reorder_point: Optional[Decimal]
    unit_cost: Decimal
    unit_cost_currency_id: int
    unit_cost_base: Decimal
    inventory_value_base: Decimal
    created_at: datetime
    updated_at: datetime


class WarehouseSummaryRead(BaseModel):
    warehouse_count: int
    stock_item_count: int
    low_stock_count: int
    quantity_on_hand_total: Decimal
    inventory_value_base: Decimal


class StockCountCreate(BaseModel):
    warehouse_id: int = Field(..., gt=0)
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_text(cls, value):
        return clean_optional(value)


class StockCountLineCreate(BaseModel):
    item_id: int = Field(..., gt=0)
    storage_location_id: int = Field(..., gt=0)
    counted_quantity: Optional[Decimal] = Field(None, ge=0)


class StockCountLineUpdate(BaseModel):
    counted_quantity: Decimal = Field(..., ge=0)


class StockCountLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_count_id: int
    item_id: int
    storage_location_id: int
    system_quantity: Decimal
    counted_quantity: Optional[Decimal]
    variance: Optional[Decimal]
    created_at: datetime
    updated_at: datetime


class StockCountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    count_number: str
    warehouse_id: int
    status: StockCountStatus
    performed_by_user_id: Optional[int]
    notes: Optional[str]
    started_at: datetime
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    lines: list[StockCountLineRead] = Field(default_factory=list)


class WarehouseSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    item_ids: list[int] = Field(default_factory=list)
    warehouse_id: Optional[int] = Field(None, gt=0)
    storage_location_id: Optional[int] = Field(None, gt=0)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
