from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class GoodsReceiptSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    limit: int = Field(20, ge=1, le=100)


class GoodsReceiptSearchHit(BaseModel):
    goods_receipt_id: int
    company_id: int
    grn_number: str
    status: str
    receipt_date: date
    delivery_note_number: str | None
    warehouse_id: int | None
    item_ids: list[int]
    item_codes: list[str]
    match_source: str
    similarity: float | None = None


class GoodsReceiptAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    goods_receipt_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"


class GoodsReceiptAskResponse(BaseModel):
    answer: str
    citations: list[int]
    used_goods_receipt_ids: list[int]
    references: list[GoodsReceiptSearchHit]
