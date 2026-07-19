"""Pydantic schemas for purchase_management endpoints."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PurchaseOrderLineCreate(BaseModel):
    item_id: int = Field(..., gt=0)
    ordered_quantity: Decimal = Field(..., gt=0)
    unit_id: int = Field(..., gt=0)
    line_description: Optional[str] = None
    unit_price: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(..., gt=0)
    notes: Optional[str] = None


class PurchasePhaseAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phase_id: int
    purchase_order_line_id: int
    allocated_quantity: Decimal
    created_at: datetime
    updated_at: datetime


class PurchaseOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_id: int
    line_number: int
    item_id: int
    ordered_quantity: Decimal
    unit_id: int
    line_description: Optional[str]
    unit_price: Decimal
    currency_id: int
    unit_price_base: Decimal
    exchange_rate_used: Decimal
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    allocations: list[PurchasePhaseAllocationRead] = Field(
        default_factory=list
    )


class PurchasePhaseItemCreate(BaseModel):
    item_id: Optional[int] = Field(None, gt=0)
    item_name: Optional[str] = Field(None, max_length=255)
    item_code: Optional[str] = Field(None, max_length=100)
    quantity: Decimal = Field(..., gt=0)
    unit: Optional[str] = Field(None, max_length=30)
    unit_price: Decimal = Field(Decimal("0"), ge=0)
    currency_id: int = Field(..., gt=0)
    unit_price_base: Decimal = Field(Decimal("0"), ge=0)
    base_currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(Decimal("1"), gt=0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def require_item_reference(self):
        if self.item_id is None and not (self.item_name or "").strip():
            raise ValueError("item_id or item_name is required")
        return self


class PurchasePhaseItemUpdate(BaseModel):
    item_id: Optional[int] = Field(None, gt=0)
    item_name: Optional[str] = Field(None, max_length=255)
    item_code: Optional[str] = Field(None, max_length=100)
    quantity: Optional[Decimal] = Field(None, gt=0)
    unit: Optional[str] = Field(None, max_length=30)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    currency_id: Optional[int] = Field(None, gt=0)
    unit_price_base: Optional[Decimal] = Field(None, ge=0)
    base_currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    notes: Optional[str] = None


class PurchasePhaseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phase_id: int
    item_id: Optional[int]
    item_name: str
    item_code: Optional[str]
    quantity: Decimal
    received_quantity: Decimal
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


class PurchasePhaseCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    expected_delivery_date: Optional[datetime] = None


class PurchasePhaseUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = None
    currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    expected_delivery_date: Optional[datetime] = None
    actual_delivery_date: Optional[datetime] = None


class PurchasePhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    allocations: list[PurchasePhaseAllocationRead] = Field(
        default_factory=list
    )
    items: list[PurchasePhaseItemRead] = Field(default_factory=list)


class PurchasePhaseSplitMove(BaseModel):
    from_phase_allocation_id: int = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)


class PurchasePhaseSplitRequest(BaseModel):
    title: Optional[str] = Field(
        None,
        max_length=255,
    )
    expected_delivery_date: datetime
    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )
    moves: list[PurchasePhaseSplitMove] = Field(
        ...,
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_split_request(self):
        self.title = (
            (self.title or "").strip()
            or None
        )
        self.reason = self.reason.strip()

        allocation_ids = [
            move.from_phase_allocation_id
            for move in self.moves
        ]

        if len(allocation_ids) != len(
            set(allocation_ids)
        ):
            raise ValueError(
                "moves must not repeat "
                "from_phase_allocation_id"
            )

        return self


class PurchasePhaseSplitCandidate(BaseModel):
    from_phase_allocation_id: int
    source_phase_id: int
    source_phase_number: int
    purchase_order_line_id: int
    item_id: int
    item_code: Optional[str]
    item_name: str
    unit_code: str
    ordered_quantity: Decimal
    allocated_quantity: Decimal
    posted_received_quantity: Decimal
    movable_quantity: Decimal


class PurchasePhaseSplitResult(BaseModel):
    phase: PurchasePhaseRead
    replayed: bool
    audit_event_id: int


class PurchaseOrderFromMRLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requisition_item_id: int = Field(..., gt=0)
    line_description: Optional[str] = None
    unit_price: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(..., gt=0)
    notes: Optional[str] = None


class PurchaseOrderFromMRCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: int = Field(..., gt=0)
    title: Optional[str] = Field(
        None,
        max_length=255,
    )
    description: Optional[str] = None
    expected_delivery_date: Optional[datetime] = None
    lines: list[
        PurchaseOrderFromMRLineCreate
    ] = Field(
        ...,
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_direct_mr_terms(self):
        requisition_item_ids = [
            line.requisition_item_id
            for line in self.lines
        ]

        if len(requisition_item_ids) != len(
            set(requisition_item_ids)
        ):
            raise ValueError(
                "Each requisition item may be "
                "selected only once"
            )

        currency_ids = {
            line.currency_id
            for line in self.lines
        }
        exchange_rates = {
            Decimal(
                str(line.exchange_rate_used)
            )
            for line in self.lines
        }

        if len(currency_ids) != 1:
            raise ValueError(
                "All direct purchase lines must "
                "use the same currency"
            )

        if len(exchange_rates) != 1:
            raise ValueError(
                "All direct purchase lines must "
                "use the same exchange rate"
            )

        return self


class PurchaseOrderCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    supplier_id: int = Field(..., gt=0)
    description: Optional[str] = None
    expected_delivery_date: Optional[datetime] = None
    lines: list[PurchaseOrderLineCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_commercial_terms(self):
        currency_ids = {line.currency_id for line in self.lines}
        exchange_rates = {
            Decimal(str(line.exchange_rate_used))
            for line in self.lines
        }

        if len(currency_ids) != 1:
            raise ValueError(
                "All purchase-order lines must use the same currency"
            )

        if len(exchange_rates) != 1:
            raise ValueError(
                "All purchase-order lines must use the same exchange rate"
            )

        return self


class PurchaseOrderUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    supplier_id: Optional[int] = Field(None, gt=0)
    supplier_name: Optional[str] = Field(None, max_length=255)
    currency_id: Optional[int] = Field(None, gt=0)
    base_currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    description: Optional[str] = None
    status: Optional[str] = None


class PurchaseOrderApproval(BaseModel):
    action: str = Field(
        ...,
        description="submit | approve | reject",
    )
    note: Optional[str] = None


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    reference_number: str
    title: Optional[str]
    rfq_id: Optional[int]
    source_material_requisition_id: Optional[int]
    winning_quotation_response_id: Optional[int]
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
    lines: list[PurchaseOrderLineRead] = Field(default_factory=list)
    phases: list[PurchasePhaseRead] = Field(default_factory=list)


class PurchaseOrderCostCreate(BaseModel):
    cost_type: str = Field(
        ...,
        description="freight | customs | tax | insurance | other",
    )
    description: Optional[str] = None
    amount: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)
    amount_base: Decimal = Field(..., ge=0)
    base_currency_id: int = Field(..., gt=0)
    exchange_rate_used: Decimal = Field(Decimal("1"), gt=0)
    allocation_method: str = Field(
        "per_value",
        description="per_item | per_value | manual",
    )


class PurchaseOrderCostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class ReceiptLinkCreate(BaseModel):
    financial_receipt_id: int = Field(..., gt=0)


class ReceiptLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_id: int
    financial_receipt_id: int
    linked_at: datetime
    linked_by_user_id: Optional[int]


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
