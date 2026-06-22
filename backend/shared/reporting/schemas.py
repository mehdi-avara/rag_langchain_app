from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class KpiRead(BaseModel):
    key: str
    label: str
    value: int | float | Decimal
    unit: str
    trend: str = "neutral"


class ReportSeriesRead(BaseModel):
    name: str
    data: list[int | float | Decimal]


class ReportRead(BaseModel):
    chart_type: str
    x: list[str]
    series: list[ReportSeriesRead]
    unit: str
    metadata: dict[str, str | int | float | Decimal | None] = Field(
        default_factory=dict
    )
