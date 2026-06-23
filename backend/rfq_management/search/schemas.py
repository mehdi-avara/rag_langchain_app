from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class RFQSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    limit: int = Field(20, ge=1, le=100)


class RFQSearchHit(BaseModel):
    rfq_id: int
    company_id: int
    rfq_number: str
    status: str
    title: str
    description: str | None
    deadline_date: date | None
    item_ids: list[int]
    item_codes: list[str]
    match_source: str
    similarity: float | None = None


class RFQAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    rfq_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"


class RFQAskResponse(BaseModel):
    answer: str
    citations: list[int]
    used_rfq_ids: list[int]
    references: list[RFQSearchHit]
