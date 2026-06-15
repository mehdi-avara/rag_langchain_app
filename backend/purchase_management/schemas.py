"""Pydantic schemas for purchase_management endpoints."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# ── PurchasePhaseItem ─────────────────────────────────────────────────────────

class PurchasePhaseItemCreate(BaseModel):
    item_name: str = Field(..., max_length=255)
    item_code: Optional[str] = Field(None, max_length=100)
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("pcs", max_length=30)
    unit_price: Decimal = Field(Decimal("0"), ge=0)
    currency_id: int
    unit_price_base: Decimal = Field(Decimal("0"), ge=0)
    base_currency_id: int
    exchange_rate_used: Decimal = Field(Decimal("1"), gt=0)
    notes: Optional[str] = None


class PurchasePhaseItemUpdate(BaseModel):
    item_name: Optional[str] = Field(None, max_length=255)
    item_code: Optional[str] = None
    quantity: Optional[Decimal] = Field(None, gt=0)
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None
    currency_id: Optional[int] = None
    unit_price_base: Optional[Decimal] = None
    base_currency_id: Optional[int] = None
    exchange_rate_used: Optional[Decimal] = None
    notes: Optional[str] = None


class PurchasePhaseItemRead(BaseModel):
    id: int
    phase_id: int
    item_name: str
    item_code: Optional[str]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    currency_id: int
    unit_price_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    line_total: Decimal
    line_total_base: Decimal
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── PurchasePhase ─────────────────────────────────────────────────────────────

class PurchasePhaseCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    currency_id: Optional[int] = None
    exchange_rate_used: Optional[Decimal] = None
    expected_delivery_date: Optional[datetime] = None


class PurchasePhaseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    currency_id: Optional[int] = None
    exchange_rate_used: Optional[Decimal] = None
    expected_delivery_date: Optional[datetime] = None
    actual_delivery_date: Optional[datetime] = None


class PurchasePhaseRead(BaseModel):
    id: int
    purchase_order_id: int
    phase_number: int
    title: Optional[str]
    description: Optional[str]
    status: str
    currency_id: Optional[int]
    exchange_rate_used: Optional[Decimal]
    expected_delivery_date: Optional[datetime]
    actual_delivery_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    items: List[PurchasePhaseItemRead] = []

    class Config:
        from_attributes = True


# ── PurchaseOrder ─────────────────────────────────────────────────────────────

class PurchaseOrderCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    supplier_name: Optional[str] = Field(None, max_length=255)
    currency_id: int
    base_currency_id: int
    exchange_rate_used: Decimal = Field(Decimal("1"), gt=0)
    description: Optional[str] = None


class PurchaseOrderUpdate(BaseModel):
    title: Optional[str] = None
    supplier_name: Optional[str] = None
    currency_id: Optional[int] = None
    base_currency_id: Optional[int] = None
    exchange_rate_used: Optional[Decimal] = None
    description: Optional[str] = None
    status: Optional[str] = None


class PurchaseOrderApproval(BaseModel):
    action: str = Field(..., description="submit | approve | reject")
    note: Optional[str] = None


class PurchaseOrderRead(BaseModel):
    id: int
    company_id: int
    reference_number: str
    title: Optional[str]
    supplier_id: Optional[int]
    supplier_name: Optional[str]
    currency_id: int
    base_currency_id: int
    exchange_rate_used: Decimal
    status: str
    approval_status: str
    description: Optional[str]
    created_by_user_id: Optional[int]
    approved_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    phases: List[PurchasePhaseRead] = []

    class Config:
        from_attributes = True


# ── PurchaseOrderCost ─────────────────────────────────────────────────────────

class PurchaseOrderCostCreate(BaseModel):
    cost_type: str = Field(..., description="freight | customs | tax | insurance | other")
    description: Optional[str] = None
    amount: Decimal = Field(..., ge=0)
    currency_id: int
    amount_base: Decimal = Field(..., ge=0)
    base_currency_id: int
    exchange_rate_used: Decimal = Field(Decimal("1"), gt=0)
    allocation_method: str = Field("per_value", description="per_item | per_value | manual")


class PurchaseOrderCostRead(BaseModel):
    id: int
    purchase_order_id: int
    cost_type: str
    description: Optional[str]
    amount: Decimal
    currency_id: int
    amount_base: Decimal
    base_currency_id: int
    exchange_rate_used: Decimal
    allocation_method: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Receipt link ──────────────────────────────────────────────────────────────

class ReceiptLinkCreate(BaseModel):
    financial_receipt_id: int


class ReceiptLinkRead(BaseModel):
    id: int
    purchase_order_id: int
    financial_receipt_id: int
    linked_at: datetime
    linked_by_user_id: Optional[int]

    class Config:
        from_attributes = True


# ── Summary ───────────────────────────────────────────────────────────────────

class PurchaseOrderSummary(BaseModel):
    purchase_order_id: int
    reference_number: str
    phase_count: int
    item_count: int
    total_in_currency: Decimal
    total_in_base: Decimal
    currency_id: int
    base_currency_id: int
    additional_costs_base: Decimal
    grand_total_base: Decimal
