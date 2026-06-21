from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import RFQStatus


def _clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class RFQItemCreate(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)
    specifications: Optional[str] = None

    @field_validator("specifications", mode="before")
    @classmethod
    def normalize_specifications(cls, value):
        return _clean_optional(value)


class RFQItemUpdate(BaseModel):
    item_id: Optional[int] = Field(None, gt=0)
    quantity: Optional[Decimal] = Field(None, gt=0)
    specifications: Optional[str] = None

    @field_validator("specifications", mode="before")
    @classmethod
    def normalize_specifications(cls, value):
        return _clean_optional(value)


class RequestForQuotationCreate(BaseModel):
    mr_id: Optional[int] = Field(None, gt=0)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    deadline_date: date
    supplier_ids: list[int] = Field(default_factory=list)
    items: list[RFQItemCreate] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        value = str(value or "").strip()
        if not value:
            raise ValueError("title is required")
        return value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _clean_optional(value)

    @field_validator("supplier_ids")
    @classmethod
    def validate_supplier_ids(cls, value):
        if any(supplier_id <= 0 for supplier_id in value):
            raise ValueError("supplier_ids must contain positive values")
        if len(value) != len(set(value)):
            raise ValueError("supplier_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_source_and_items(self):
        if self.mr_id is None and not self.items:
            raise ValueError("items are required when mr_id is not provided")
        if self.mr_id is not None and self.items:
            raise ValueError("items must be empty when creating an RFQ from an MR")
        return self


class RequestForQuotationUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    deadline_date: Optional[date] = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        if not value:
            raise ValueError("title cannot be empty")
        return value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _clean_optional(value)


class RFQSupplierCreate(BaseModel):
    supplier_id: int = Field(..., gt=0)


class QuotationResponseItemCreate(BaseModel):
    rfq_item_id: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)
    unit_price_base: Decimal = Field(..., ge=0)
    base_currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(..., gt=0)
    lead_time_days: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class QuotationResponseItemUpdate(BaseModel):
    rfq_item_id: Optional[int] = Field(None, gt=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    currency_id: Optional[int] = Field(None, gt=0)
    unit_price_base: Optional[Decimal] = Field(None, ge=0)
    base_currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    lead_time_days: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class QuotationResponseCreate(BaseModel):
    supplier_id: int = Field(..., gt=0)
    received_at: Optional[datetime] = None
    valid_until: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_days: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    items: list[QuotationResponseItemCreate] = Field(..., min_length=1)

    @field_validator("payment_terms", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return _clean_optional(value)

    @model_validator(mode="after")
    def validate_item_uniqueness(self):
        rfq_item_ids = [item.rfq_item_id for item in self.items]
        if len(rfq_item_ids) != len(set(rfq_item_ids)):
            raise ValueError("quotation response items must not repeat rfq_item_id")
        return self


class QuotationResponseUpdate(BaseModel):
    received_at: Optional[datetime] = None
    valid_until: Optional[date] = None
    payment_terms: Optional[str] = None
    delivery_days: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None

    @field_validator("payment_terms", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return _clean_optional(value)


class WinningQuotationSelect(BaseModel):
    quotation_response_id: int = Field(..., gt=0)


class RFQItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_name: str
    unit_id: Optional[int]
    unit_code: str
    quantity: Decimal
    specifications: Optional[str]
    created_at: datetime
    updated_at: datetime


class RFQSupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_id: int
    supplier_id: Optional[int]
    supplier_code: Optional[str]
    supplier_name: str
    sent_at: Optional[datetime]
    response_status: str
    created_at: datetime
    updated_at: datetime


class QuotationResponseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quotation_response_id: int
    rfq_item_id: int
    unit_price: Decimal
    currency_id: int
    unit_price_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    lead_time_days: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class QuotationResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfq_id: int
    supplier_id: Optional[int]
    supplier_code: Optional[str]
    supplier_name: str
    received_at: datetime
    valid_until: Optional[date]
    payment_terms: Optional[str]
    delivery_days: Optional[int]
    notes: Optional[str]
    is_winner: bool
    selected_by_user_id: Optional[int]
    selected_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    items: list[QuotationResponseItemRead] = Field(default_factory=list)


class RequestForQuotationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    rfq_number: str
    mr_id: Optional[int]
    title: str
    description: Optional[str]
    deadline_date: date
    status: str
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    suppliers: list[RFQSupplierRead] = Field(default_factory=list)
    items: list[RFQItemRead] = Field(default_factory=list)
    responses: list[QuotationResponseRead] = Field(default_factory=list)


class RFQComparisonSupplier(BaseModel):
    rfq_supplier_id: int
    supplier_id: Optional[int]
    supplier_code: Optional[str]
    supplier_name: str
    response_status: str
    response_id: Optional[int]
    received_at: Optional[datetime]
    valid_until: Optional[date]
    payment_terms: Optional[str]
    delivery_days: Optional[int]
    is_winner: bool


class RFQComparisonQuote(BaseModel):
    quotation_response_id: int
    supplier_id: Optional[int]
    supplier_code: Optional[str]
    supplier_name: str
    is_winner: bool
    unit_price: Decimal
    currency_id: int
    unit_price_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    lead_time_days: Optional[int]
    notes: Optional[str]


class RFQComparisonItem(BaseModel):
    rfq_item_id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_name: str
    unit_code: str
    quantity: Decimal
    specifications: Optional[str]
    quotes: list[RFQComparisonQuote] = Field(default_factory=list)


class RFQComparisonRead(BaseModel):
    rfq_id: int
    rfq_number: str
    mr_id: Optional[int]
    title: str
    deadline_date: date
    status: RFQStatus
    suppliers: list[RFQComparisonSupplier] = Field(default_factory=list)
    items: list[RFQComparisonItem] = Field(default_factory=list)
