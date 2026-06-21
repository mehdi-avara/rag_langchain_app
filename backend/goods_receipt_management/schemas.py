from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import GoodsReceiptStatus


def clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class GoodsReceiptItemCreate(BaseModel):
    purchase_phase_item_id: int = Field(..., gt=0)
    item_id: Optional[int] = Field(None, gt=0)
    received_quantity: Decimal = Field(..., gt=0)
    accepted_quantity: Decimal = Field(..., ge=0)
    rejected_quantity: Decimal = Field(..., ge=0)
    rejection_reason: Optional[str] = None
    storage_location_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("rejection_reason", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return clean_optional(value)

    @model_validator(mode="after")
    def validate_quantities(self):
        if self.accepted_quantity + self.rejected_quantity != self.received_quantity:
            raise ValueError(
                "accepted_quantity plus rejected_quantity must equal received_quantity"
            )

        if self.rejected_quantity > 0 and not self.rejection_reason:
            raise ValueError(
                "rejection_reason is required when rejected_quantity is greater than zero"
            )

        return self


class GoodsReceiptItemUpdate(BaseModel):
    item_id: Optional[int] = Field(None, gt=0)
    received_quantity: Optional[Decimal] = Field(None, gt=0)
    accepted_quantity: Optional[Decimal] = Field(None, ge=0)
    rejected_quantity: Optional[Decimal] = Field(None, ge=0)
    rejection_reason: Optional[str] = None
    storage_location_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("rejection_reason", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return clean_optional(value)


class GoodsReceiptCreate(BaseModel):
    purchase_phase_id: int = Field(..., gt=0)
    receipt_date: date
    delivery_note_number: Optional[str] = Field(None, max_length=100)
    warehouse_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None
    items: list[GoodsReceiptItemCreate] = Field(default_factory=list)

    @field_validator("delivery_note_number", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return clean_optional(value)

    @model_validator(mode="after")
    def validate_item_uniqueness(self):
        ids = [item.purchase_phase_item_id for item in self.items]

        if len(ids) != len(set(ids)):
            raise ValueError("items must not repeat purchase_phase_item_id")

        return self


class GoodsReceiptUpdate(BaseModel):
    receipt_date: Optional[date] = None
    delivery_note_number: Optional[str] = Field(None, max_length=100)
    warehouse_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("delivery_note_number", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return clean_optional(value)


class GoodsReceiptItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goods_receipt_note_id: int
    purchase_phase_item_id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_name: str
    unit_code: str
    received_quantity: Decimal
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    rejection_reason: Optional[str]
    storage_location_id: Optional[int]
    unit_cost: Decimal
    currency_id: int
    unit_cost_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class GoodsReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    grn_number: str
    purchase_order_id: int
    purchase_phase_id: int
    received_by_user_id: Optional[int]
    receipt_date: date
    delivery_note_number: Optional[str]
    warehouse_id: Optional[int]
    status: GoodsReceiptStatus
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: list[GoodsReceiptItemRead] = Field(default_factory=list)
