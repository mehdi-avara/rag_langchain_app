from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import SupplierStatus, SupplierType


def _clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class SupplierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    supplier_type: SupplierType = SupplierType.LOCAL
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    tax_id: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=512)
    status: SupplierStatus = SupplierStatus.PENDING
    notes: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if value is None:
            raise ValueError("name is required")
        value = str(value).strip()
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("country", "city", "address", "tax_id", "website", "notes", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value):
        return _clean_optional(value)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    supplier_type: Optional[SupplierType] = None
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    tax_id: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=512)
    status: Optional[SupplierStatus] = None
    notes: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        if not value:
            raise ValueError("name cannot be empty")
        return value

    @field_validator("country", "city", "address", "tax_id", "website", "notes", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value):
        return _clean_optional(value)


class SupplierContactCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    is_primary: bool = False
    notes: Optional[str] = None

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value):
        value = str(value or "").strip()
        if not value:
            raise ValueError("full_name is required")
        return value

    @field_validator("job_title", "phone", "email", "notes", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value):
        return _clean_optional(value)


class SupplierContactUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    is_primary: Optional[bool] = None
    notes: Optional[str] = None

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        if not value:
            raise ValueError("full_name cannot be empty")
        return value

    @field_validator("job_title", "phone", "email", "notes", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value):
        return _clean_optional(value)


class SupplierCategoryCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=255)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        value = str(value or "").strip()
        if not value:
            raise ValueError("category is required")
        return value


class SupplierDocumentCreate(BaseModel):
    asset_id: Optional[int] = Field(None, gt=0)
    document_type: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None
    expires_at: Optional[date] = None

    @field_validator("document_type", "title", mode="before")
    @classmethod
    def normalize_required_fields(cls, value):
        value = str(value or "").strip()
        if not value:
            raise ValueError("value is required")
        return value

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class SupplierEvaluationCreate(BaseModel):
    quality_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    delivery_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    price_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    service_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    notes: Optional[str] = None
    evaluation_date: date

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)

    @model_validator(mode="after")
    def require_one_score(self):
        values = [
            self.quality_score,
            self.delivery_score,
            self.price_score,
            self.service_score,
        ]
        if all(value is None for value in values):
            raise ValueError("at least one score is required")
        return self


class SupplierEvaluationUpdate(BaseModel):
    quality_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    delivery_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    price_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    service_score: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("100"))
    notes: Optional[str] = None
    evaluation_date: Optional[date] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _clean_optional(value)


class SupplierContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    full_name: str
    job_title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SupplierCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    category: str
    created_at: datetime


class SupplierDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    asset_id: Optional[int] = None
    document_type: str
    title: str
    notes: Optional[str] = None
    expires_at: Optional[date] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime


class SupplierEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    evaluator_user_id: Optional[int] = None
    quality_score: Optional[Decimal] = None
    delivery_score: Optional[Decimal] = None
    price_score: Optional[Decimal] = None
    service_score: Optional[Decimal] = None
    notes: Optional[str] = None
    evaluation_date: date
    created_at: datetime
    updated_at: datetime


class SupplierPerformanceOut(BaseModel):
    supplier_id: int
    evaluation_count: int
    quality_score: Optional[Decimal] = None
    delivery_score: Optional[Decimal] = None
    price_score: Optional[Decimal] = None
    service_score: Optional[Decimal] = None
    overall_score: Optional[Decimal] = None


class SupplierOut(BaseModel):
    id: int
    company_id: int
    code: str
    name: str
    supplier_type: SupplierType
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    website: Optional[str] = None
    status: SupplierStatus
    notes: Optional[str] = None
    created_by_user_id: Optional[int] = None
    embedding_status: Literal["available", "pending"]
    created_at: datetime
    updated_at: datetime
    contacts: list[SupplierContactOut] = Field(default_factory=list)
    categories: list[SupplierCategoryOut] = Field(default_factory=list)
    documents: list[SupplierDocumentOut] = Field(default_factory=list)
    performance: Optional[SupplierPerformanceOut] = None


class SupplierSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: list[int] = Field(default_factory=list)
    status: Optional[SupplierStatus] = None
    supplier_type: Optional[SupplierType] = None
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"
    limit: int = Field(default=20, ge=1, le=200)


class SupplierSearchHit(BaseModel):
    supplier_id: int
    company_id: int
    code: str
    name: str
    supplier_type: SupplierType
    status: SupplierStatus
    country: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None
    match_source: Literal["semantic", "text", "text_fallback"]
    similarity: Optional[float] = None


class SupplierAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    supplier_ids: list[int] = Field(default_factory=list)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"


class SupplierAskResponse(BaseModel):
    answer: str
    citations: list[int] = Field(default_factory=list)
    used_supplier_ids: list[int] = Field(default_factory=list)
    references: list[SupplierSearchHit] = Field(default_factory=list)
