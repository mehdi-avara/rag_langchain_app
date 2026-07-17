from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequisitionSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    limit: int = Field(20, ge=1, le=100)


class RequisitionSearchHit(BaseModel):
    requisition_id: int
    company_id: int
    mr_number: str
    status: str
    priority: str
    reason: str
    needed_by_date: Optional[date]
    item_ids: list[int]
    item_codes: list[str]
    match_source: str
    similarity: float | None = None


class RequisitionAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    requisition_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"


class RequisitionAskResponse(BaseModel):
    answer: str
    citations: list[int]
    used_requisition_ids: list[int]
    references: list[RequisitionSearchHit]
