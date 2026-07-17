from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import MaterialRequisitionPriority


class MaterialRequisitionItemCreate(BaseModel):
    item_id: int = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)
    estimated_unit_cost: Optional[Decimal] = Field(None, ge=0)
    currency_id: Optional[int] = Field(None, gt=0)
    estimated_unit_cost_base: Optional[Decimal] = Field(None, ge=0)
    base_currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_estimated_cost_fields(self):
        values = [
            self.estimated_unit_cost,
            self.currency_id,
            self.estimated_unit_cost_base,
            self.base_currency_id,
            self.exchange_rate_used,
        ]

        if all(value is None for value in values):
            return self

        if any(value is None for value in values):
            raise ValueError(
                "estimated_unit_cost, currency_id, estimated_unit_cost_base, "
                "base_currency_id, and exchange_rate_used must be provided together"
            )

        return self


class MaterialRequisitionItemUpdate(BaseModel):
    item_id: Optional[int] = Field(None, gt=0)
    quantity: Optional[Decimal] = Field(None, gt=0)
    estimated_unit_cost: Optional[Decimal] = Field(None, ge=0)
    currency_id: Optional[int] = Field(None, gt=0)
    estimated_unit_cost_base: Optional[Decimal] = Field(None, ge=0)
    base_currency_id: Optional[int] = Field(None, gt=0)
    exchange_rate_used: Optional[Decimal] = Field(None, gt=0)
    notes: Optional[str] = None


class MaterialRequisitionCreate(BaseModel):
    department_id: Optional[int] = Field(None, gt=0)
    needed_by_date: Optional[date] = None
    reason: str = Field(..., min_length=1)
    priority: MaterialRequisitionPriority = MaterialRequisitionPriority.NORMAL
    notes: Optional[str] = None
    items: List[MaterialRequisitionItemCreate] = Field(default_factory=list)


class MaterialRequisitionUpdate(BaseModel):
    department_id: Optional[int] = Field(None, gt=0)
    needed_by_date: Optional[date] = None
    reason: Optional[str] = Field(None, min_length=1)
    priority: Optional[MaterialRequisitionPriority] = None
    notes: Optional[str] = None


class RequisitionApprovalAction(BaseModel):
    action: Literal["start_review", "approve", "reject"]
    note: Optional[str] = None


class MaterialRequisitionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_requisition_id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_name: str
    unit_id: Optional[int]
    unit_code: str
    quantity: Decimal
    estimated_unit_cost: Optional[Decimal]
    currency_id: Optional[int]
    estimated_unit_cost_base: Optional[Decimal]
    base_currency_id: Optional[int]
    exchange_rate_used: Optional[Decimal]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class MaterialRequisitionStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_requisition_id: int
    from_status: Optional[str]
    to_status: str
    action: str
    note: Optional[str]
    changed_by_user_id: Optional[int]
    changed_at: datetime


class MaterialRequisitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    mr_number: str
    requested_by_user_id: Optional[int]
    department_id: Optional[int]
    needed_by_date: Optional[date]
    reason: str
    priority: str
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[MaterialRequisitionItemRead] = Field(default_factory=list)
    status_history: List[MaterialRequisitionStatusHistoryRead] = Field(
        default_factory=list
    )
