from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExportFormat(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class ExportRequest(BaseModel):
    format: ExportFormat
    filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] | None = Field(default=None, max_length=50)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: list[str] | None):
        if value is None:
            return value

        normalized = [str(column or "").strip() for column in value]

        if not normalized or any(not column for column in normalized):
            raise ValueError("columns must contain non-empty values")

        if len(set(normalized)) != len(normalized):
            raise ValueError("columns must not contain duplicates")

        return normalized


class ExportTaskOut(BaseModel):
    task_id: str
    task_type: str
    status: str
    audit_id: int
