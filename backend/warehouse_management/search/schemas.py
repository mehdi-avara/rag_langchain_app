from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class WarehouseSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    warehouse_id: int | None = Field(None, gt=0)
    storage_location_id: int | None = Field(None, gt=0)
    limit: int = Field(20, ge=1, le=100)


class WarehouseSearchHit(BaseModel):
    stock_item_id: int
    company_id: int
    item_id: int
    item_code: str
    item_name: str
    unit_code: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    storage_location_id: int
    storage_location_code: str
    storage_location_name: str
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    quantity_available: Decimal
    unit_cost: Decimal
    unit_cost_base: Decimal
    inventory_value_base: Decimal
    created_at: datetime
    updated_at: datetime
    match_source: str
    similarity: float | None = None


class WarehouseAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    stock_item_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    warehouse_id: int | None = Field(None, gt=0)
    storage_location_id: int | None = Field(None, gt=0)


class WarehouseAskResponse(BaseModel):
    answer: str
    citations: list[int]
    used_stock_item_ids: list[int]
    references: list[WarehouseSearchHit]
