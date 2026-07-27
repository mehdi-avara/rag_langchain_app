"""Pydantic schemas for purchase_management endpoints."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

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


class PurchasePhaseAllocationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_id: int = Field(..., gt=0)
    allocated_quantity: Decimal = Field(
        ...,
        gt=0,
    )


class PurchaseOrderLineMutationCreate(
    PurchaseOrderLineCreate
):
    model_config = ConfigDict(extra="forbid")

    allocations: list[
        PurchasePhaseAllocationWrite
    ] = Field(
        ...,
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_allocations(self):
        phase_ids = [
            allocation.phase_id
            for allocation in self.allocations
        ]

        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError(
                "Each delivery phase may appear "
                "only once"
            )

        total = sum(
            (
                allocation.allocated_quantity
                for allocation in self.allocations
            ),
            Decimal("0"),
        )

        if total != self.ordered_quantity:
            raise ValueError(
                "Allocation total must equal "
                "ordered quantity"
            )

        return self


class PurchaseOrderLineMutationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: Optional[int] = Field(
        None,
        gt=0,
    )
    ordered_quantity: Optional[Decimal] = Field(
        None,
        gt=0,
    )
    unit_id: Optional[int] = Field(
        None,
        gt=0,
    )
    line_description: Optional[str] = None
    unit_price: Optional[Decimal] = Field(
        None,
        ge=0,
    )
    currency_id: Optional[int] = Field(
        None,
        gt=0,
    )
    exchange_rate_used: Optional[
        Decimal
    ] = Field(
        None,
        gt=0,
    )
    notes: Optional[str] = None
    allocations: Optional[
        list[PurchasePhaseAllocationWrite]
    ] = None

    @model_validator(mode="after")
    def validate_allocation_scope(self):
        if self.allocations is None:
            return self

        if not self.allocations:
            raise ValueError(
                "At least one allocation is required"
            )

        phase_ids = [
            allocation.phase_id
            for allocation in self.allocations
        ]

        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError(
                "Each delivery phase may appear "
                "only once"
            )

        return self


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


class PurchasePhaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(
        None,
        max_length=255,
    )
    description: Optional[str] = None
    expected_delivery_date: Optional[
        datetime
    ] = None

class PurchasePhaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(
        None,
        max_length=255,
    )
    description: Optional[str] = None
    expected_delivery_date: Optional[
        datetime
    ] = None

class PurchasePhaseRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    purchase_order_id: int
    phase_number: int
    title: Optional[str]
    description: Optional[str]
    status: str
    expected_delivery_date: Optional[
        datetime
    ]
    created_at: datetime
    updated_at: datetime
    allocations: list[
        PurchasePhaseAllocationRead
    ] = Field(
        default_factory=list
    )

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
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(
        None,
        max_length=255,
    )
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
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(
        None,
        max_length=255,
    )
    supplier_id: Optional[int] = Field(
        None,
        gt=0,
    )
    description: Optional[str] = None


class PurchaseOrderSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(
        None,
        max_length=2000,
    )


class PurchaseOrderApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    note: Optional[str] = Field(
        None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_rejection_note(self):
        if (
            self.action == "reject"
            and not (self.note or "").strip()
        ):
            raise ValueError(
                "A rejection note is required"
            )

        if self.note is not None:
            self.note = self.note.strip() or None

        return self


class PurchaseOrderAmendmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def normalize_reason(self):
        self.reason = self.reason.strip()

        if not self.reason:
            raise ValueError(
                "Amendment reason is required"
            )

        return self


class PurchaseOrderAmendmentSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(
        None,
        max_length=2000,
    )


class PurchaseOrderAmendmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    note: Optional[str] = Field(
        None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_decision_note(self):
        if (
            self.action == "reject"
            and not (self.note or "").strip()
        ):
            raise ValueError(
                "A rejection note is required"
            )

        if self.note is not None:
            self.note = self.note.strip() or None

        return self


class PurchaseOrderAmendmentRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    company_id: int
    purchase_order_id: int
    amendment_number: int
    status: str
    reason: str
    before_snapshot: dict
    proposed_snapshot: Optional[dict]
    submission_note: Optional[str]
    decision_note: Optional[str]
    created_by_user_id: Optional[int]
    submitted_by_user_id: Optional[int]
    decided_by_user_id: Optional[int]
    created_at: datetime
    submitted_at: Optional[datetime]
    decided_at: Optional[datetime]
    updated_at: datetime


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    company_id: int
    reference_number: str
    title: Optional[str]
    source_rfq_id: Optional[int]
    source_material_requisition_id: Optional[
        int
    ]
    supplier_id: int
    supplier_name: Optional[str]
    status: str
    approval_status: str
    description: Optional[str]
    created_by_user_id: Optional[int]
    approved_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    active_amendment_id: Optional[int]
    active_amendment_status: Optional[str]
    amendment_count: int
    lines: list[
        PurchaseOrderLineRead
    ] = Field(
        default_factory=list
    )
    phases: list[
        PurchasePhaseRead
    ] = Field(
        default_factory=list
    )

class PurchaseOrderCostCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    cost_type: Literal[
        "goods",
        "freight",
        "customs",
        "tax",
        "insurance",
        "other",
    ]

    description: Optional[str] = None

    predicted_amount: Optional[
        Decimal
    ] = Field(
        None,
        ge=0,
    )
    predicted_currency_id: Optional[
        int
    ] = Field(
        None,
        gt=0,
    )

    amount: Optional[Decimal] = Field(
        None,
        ge=0,
        deprecated=True,
        description=(
            "Deprecated alias for "
            "predicted_amount"
        ),
    )
    currency_id: Optional[int] = Field(
        None,
        gt=0,
        deprecated=True,
        description=(
            "Deprecated alias for "
            "predicted_currency_id"
        ),
    )
    allocation_method: Optional[
        str
    ] = Field(
        None,
        deprecated=True,
    )

    @model_validator(mode="after")
    def normalize_predicted_money(self):
        if (
            self.predicted_amount
            is not None
            and self.amount is not None
            and self.predicted_amount
            != self.amount
        ):
            raise ValueError(
                "amount and predicted_amount "
                "must match"
            )

        if (
            self.predicted_currency_id
            is not None
            and self.currency_id is not None
            and self.predicted_currency_id
            != self.currency_id
        ):
            raise ValueError(
                "currency_id and "
                "predicted_currency_id "
                "must match"
            )

        if self.predicted_amount is None:
            self.predicted_amount = (
                self.amount
            )

        if (
            self.predicted_currency_id
            is None
        ):
            self.predicted_currency_id = (
                self.currency_id
            )

        if (
            self.predicted_amount is None
            or self.predicted_currency_id
            is None
        ):
            raise ValueError(
                "predicted_amount and "
                "predicted_currency_id "
                "are required"
            )

        self.amount = self.predicted_amount
        self.currency_id = (
            self.predicted_currency_id
        )

        return self



class PurchaseOrderCostUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    cost_type: Optional[
        Literal[
            "goods",
            "freight",
            "customs",
            "tax",
            "insurance",
            "other",
        ]
    ] = None

    description: Optional[str] = None

    predicted_amount: Optional[
        Decimal
    ] = Field(
        None,
        ge=0,
    )
    predicted_currency_id: Optional[
        int
    ] = Field(
        None,
        gt=0,
    )

    amount: Optional[Decimal] = Field(
        None,
        ge=0,
        deprecated=True,
        description=(
            "Deprecated alias for "
            "predicted_amount"
        ),
    )
    currency_id: Optional[int] = Field(
        None,
        gt=0,
        deprecated=True,
        description=(
            "Deprecated alias for "
            "predicted_currency_id"
        ),
    )
    allocation_method: Optional[
        str
    ] = Field(
        None,
        deprecated=True,
    )

    @model_validator(mode="after")
    def normalize_predicted_aliases(self):
        if (
            self.predicted_amount
            is not None
            and self.amount is not None
            and self.predicted_amount
            != self.amount
        ):
            raise ValueError(
                "amount and predicted_amount "
                "must match"
            )

        if (
            self.predicted_currency_id
            is not None
            and self.currency_id is not None
            and self.predicted_currency_id
            != self.currency_id
        ):
            raise ValueError(
                "currency_id and "
                "predicted_currency_id "
                "must match"
            )

        if (
            self.predicted_amount is None
            and self.amount is not None
        ):
            self.predicted_amount = (
                self.amount
            )

        if (
            self.predicted_currency_id
            is None
            and self.currency_id
            is not None
        ):
            self.predicted_currency_id = (
                self.currency_id
            )

        return self



class PurchaseOrderCostMoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(..., ge=0)
    currency_id: int = Field(..., gt=0)


class PurchaseOrderCostConfirmActual(
    PurchaseOrderCostMoneyInput
):
    pass


class PurchaseOrderCostPaymentRead(BaseModel):
    cost_id: int
    settlement_target_base: Decimal
    paid_base: Decimal
    outstanding_base: Decimal
    variance_base: Optional[Decimal] = None
    payment_state: Literal[
        "unpaid",
        "advance_paid",
        "partially_paid",
        "paid",
        "payment_review_required",
        "not_tracked",
    ]


class PurchaseOrderPaymentSummaryRead(BaseModel):
    purchase_order_id: int
    base_currency_id: int
    predicted_total_base: Decimal
    predicted_by_cost_type_base: dict[
        str,
        Decimal,
    ]
    actual_total_base: Decimal
    unpredicted_total_base: Decimal
    paid_total_base: Decimal
    outstanding_total_base: Decimal
    variance_total_base: Decimal
    payment_tracking: Literal[
        "tracked",
        "not_tracked",
    ]
    costs: list[
        PurchaseOrderCostPaymentRead
    ] = Field(default_factory=list)


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

    predicted_amount: Optional[Decimal] = None
    predicted_currency_id: Optional[int] = None
    predicted_amount_base: Optional[Decimal] = None
    predicted_exchange_rate_used: Optional[
        Decimal
    ] = None

    actual_amount: Optional[Decimal] = None
    actual_currency_id: Optional[int] = None
    actual_amount_base: Optional[Decimal] = None
    actual_exchange_rate_used: Optional[
        Decimal
    ] = None

    created_by_user_id: Optional[int] = None
    actual_confirmed_at: Optional[datetime] = None
    actual_confirmed_by_user_id: Optional[
        int
    ] = None

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
    allocation_status: str = "legacy_unallocated"


class PurchaseOrderSummary(BaseModel):
    purchase_order_id: int
    reference_number: str
    phase_count: int
    item_count: int
    total_in_currency: Decimal
    total_in_base: Decimal
    currency_id: Optional[int]
    base_currency_id: int
    additional_costs_base: Decimal
    grand_total_base: Decimal
