from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import ItemType, UnitType


def _clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _required_text(value, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


class ItemCategoryCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _clean_optional(value)


class ItemCategoryUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    parent_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        if value is None:
            return None
        return _required_text(value, info.field_name)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _clean_optional(value)


class UnitCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    unit_type: UnitType = UnitType.COUNT

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        return _required_text(value, info.field_name)


class UnitUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=30)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    unit_type: Optional[UnitType] = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        if value is None:
            return None
        return _required_text(value, info.field_name)


class ItemCreate(BaseModel):
    item_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    category_id: int = Field(..., gt=0)
    unit_id: int = Field(..., gt=0)
    model_id: Optional[int] = Field(None, gt=0)
    specs: dict = Field(default_factory=dict)
    barcode: Optional[str] = Field(None, max_length=255)
    qr_code: Optional[str] = Field(None, max_length=255)
    item_type: ItemType = ItemType.MATERIAL
    is_active: bool = True
    is_critical: bool = False
    lead_time_days: Optional[int] = Field(None, ge=0)

    @field_validator("item_code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("description", "barcode", "qr_code", mode="before")
    @classmethod
    def normalize_optional(cls, value):
        return _clean_optional(value)


class ItemUpdate(BaseModel):
    item_code: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category_id: Optional[int] = Field(None, gt=0)
    unit_id: Optional[int] = Field(None, gt=0)
    model_id: Optional[int] = Field(None, gt=0)
    specs: Optional[dict] = None
    barcode: Optional[str] = Field(None, max_length=255)
    qr_code: Optional[str] = Field(None, max_length=255)
    item_type: Optional[ItemType] = None
    is_active: Optional[bool] = None
    is_critical: Optional[bool] = None
    lead_time_days: Optional[int] = Field(None, ge=0)

    @field_validator("item_code", "name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        if value is None:
            return None
        return _required_text(value, info.field_name)

    @field_validator("description", "barcode", "qr_code", mode="before")
    @classmethod
    def normalize_optional(cls, value):
        return _clean_optional(value)


class ItemAlternativeCreate(BaseModel):
    alt_code: str = Field(..., min_length=1, max_length=100)
    alt_name: str = Field(..., min_length=1, max_length=255)
    supplier_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("alt_code", "alt_name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class ItemAlternativeUpdate(BaseModel):
    alt_code: Optional[str] = Field(None, min_length=1, max_length=100)
    alt_name: Optional[str] = Field(None, min_length=1, max_length=255)
    supplier_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("alt_code", "alt_name", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        if value is None:
            return None
        return _required_text(value, info.field_name)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class ItemDocumentCreate(BaseModel):
    asset_id: Optional[int] = Field(None, gt=0)
    document_type: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None

    @field_validator("document_type", "title", mode="before")
    @classmethod
    def normalize_required(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class ItemCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    parent_id: Optional[int] = None
    code: str
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ItemCategoryTreeOut(ItemCategoryOut):
    children: list["ItemCategoryTreeOut"] = Field(default_factory=list)


ItemCategoryTreeOut.model_rebuild()


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    name: str
    unit_type: UnitType
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ItemAlternativeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    supplier_id: Optional[int] = None
    alt_code: str
    alt_name: str
    notes: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ItemDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    asset_id: Optional[int] = None
    document_type: str
    title: str
    notes: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime


class ItemModelSummaryOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    type: Optional[str] = None


class ItemOut(BaseModel):
    id: int
    company_id: int
    item_code: str
    name: str
    description: Optional[str] = None
    category_id: int
    unit_id: int
    model_id: Optional[int] = None
    model: Optional[ItemModelSummaryOut] = None
    specs: dict
    barcode: Optional[str] = None
    qr_code: Optional[str] = None
    item_type: ItemType
    is_active: bool
    is_critical: bool
    lead_time_days: Optional[int] = None
    created_by_user_id: Optional[int] = None
    embedding_status: Literal["available", "pending"]
    created_at: datetime
    updated_at: datetime
    category: ItemCategoryOut
    unit: UnitOut
    alternatives: list[ItemAlternativeOut] = Field(default_factory=list)
    documents: list[ItemDocumentOut] = Field(default_factory=list)


class ItemSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: list[int] = Field(default_factory=list)
    category_id: Optional[int] = Field(None, gt=0)
    item_type: Optional[ItemType] = None
    is_active: Optional[bool] = None
    model_id: Optional[int] = Field(None, gt=0)
    model: Optional[str] = Field(None, min_length=1)
    manufacturer: Optional[str] = Field(None, min_length=1)
    model_type: Optional[str] = Field(None, min_length=1)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"
    limit: int = Field(default=20, ge=1, le=200)


class ItemSearchHit(BaseModel):
    item_id: int
    company_id: int
    item_code: str
    name: str
    description: Optional[str] = None
    category_id: int
    unit_id: int
    model_id: Optional[int] = None
    model: Optional[ItemModelSummaryOut] = None
    item_type: ItemType
    is_active: bool
    is_critical: bool
    match_source: Literal["semantic", "text", "text_fallback"]
    similarity: Optional[float] = None


class ItemAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    item_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"


class ItemAskResponse(BaseModel):
    answer: str
    citations: list[int] = Field(default_factory=list)
    used_item_ids: list[int] = Field(default_factory=list)
    references: list[ItemSearchHit] = Field(default_factory=list)


class ItemImportRequest(BaseModel):
    asset_id: int = Field(..., gt=0)


class ItemImportTaskOut(BaseModel):
    task_id: str
    task_type: str
    status: str
