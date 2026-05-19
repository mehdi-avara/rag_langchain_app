from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import BuyingCostAllocationMethod, BuyingCostType, BuyingProcessStatus, BuyingReceiptPurpose


class BuyingProcessBase(BaseModel):
    title: str = Field(..., min_length=1)
    supplier_name: Optional[str] = None
    status: BuyingProcessStatus = BuyingProcessStatus.DRAFT
    currency: str = Field(..., min_length=1, max_length=12)
    base_currency: str = Field(..., min_length=1, max_length=12)
    exchange_rate_to_base: Decimal = Field(..., gt=Decimal("0"))
    purchase_date: datetime
    description: Optional[str] = None
    affects_warehouse: bool = False


class BuyingProcessCreate(BuyingProcessBase):
    pass


class BuyingProcessUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    supplier_name: Optional[str] = None
    status: Optional[BuyingProcessStatus] = None
    currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    base_currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    purchase_date: Optional[datetime] = None
    description: Optional[str] = None
    affects_warehouse: Optional[bool] = None


class BuyingProcessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    owner_id: int
    title: str
    supplier_name: Optional[str] = None
    status: BuyingProcessStatus
    currency: str
    base_currency: str
    exchange_rate_to_base: Decimal
    purchase_date: datetime
    description: Optional[str] = None
    affects_warehouse: bool
    warehouse_applied_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BuyingProcessListOut(BuyingProcessOut):
    item_count: int = 0
    total_quantity: int = 0
    grand_total_base: Decimal = Decimal("0")


class BuyingProcessItemCreate(BaseModel):
    model_id: int
    color: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=Decimal("0"))
    currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))


class BuyingProcessItemUpdate(BaseModel):
    model_id: Optional[int] = None
    color: Optional[str] = Field(default=None, min_length=1)
    quantity: Optional[int] = Field(default=None, gt=0)
    unit_price: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))


class BuyingProcessItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    buying_process_id: int
    model_id: int
    color: str
    quantity: int
    unit_price: Decimal
    currency: str
    exchange_rate_to_base: Decimal
    unit_price_base: Decimal
    line_total: Decimal
    line_total_base: Decimal
    allocated_cost_base: Decimal
    final_unit_cost_base: Decimal
    created_at: datetime
    updated_at: datetime


class BuyingProcessReceiptLinkCreate(BaseModel):
    receipt_id: int
    purpose: BuyingReceiptPurpose
    note: Optional[str] = None


class BuyingProcessReceiptLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    buying_process_id: int
    receipt_id: int
    linked_by_user_id: int
    purpose: BuyingReceiptPurpose
    note: Optional[str] = None
    created_at: datetime


class BuyingProcessCostCreate(BaseModel):
    receipt_id: Optional[int] = None
    cost_type: BuyingCostType
    amount: Decimal = Field(..., ge=Decimal("0"))
    currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    allocation_method: BuyingCostAllocationMethod
    manual_allocations_json: Optional[Dict[int, Decimal]] = None
    description: Optional[str] = None


class BuyingProcessCostUpdate(BaseModel):
    receipt_id: Optional[int] = None
    cost_type: Optional[BuyingCostType] = None
    amount: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    currency: Optional[str] = Field(default=None, min_length=1, max_length=12)
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    allocation_method: Optional[BuyingCostAllocationMethod] = None
    manual_allocations_json: Optional[Dict[int, Decimal]] = None
    description: Optional[str] = None


class BuyingProcessCostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    buying_process_id: int
    receipt_id: Optional[int] = None
    cost_type: BuyingCostType
    amount: Decimal
    currency: str
    exchange_rate_to_base: Decimal
    amount_base: Decimal
    allocation_method: BuyingCostAllocationMethod
    manual_allocations_json: Optional[Dict[str, str]] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BuyingProcessItemCostSummaryOut(BaseModel):
    item_id: int
    model_id: int
    color: str
    quantity: int
    line_total_base: Decimal
    allocated_cost_base: Decimal
    final_unit_cost_base: Decimal


class BuyingProcessSummaryOut(BaseModel):
    process_id: int
    product_total_base: Decimal
    extra_cost_total_base: Decimal
    grand_total_base: Decimal
    receipt_total_base: Decimal
    unmatched_receipt_amount_base: Decimal
    total_quantity: int
    items: List[BuyingProcessItemCostSummaryOut]

