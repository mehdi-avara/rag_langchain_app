from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, validator

from Models import CommentType
from schemas.comment import CommentCreate

from .models import FinancialAccessMethod, FinancialCurrency, FinancialDirection


def normalize_receipt_date(value):
    if value is None:
        return value

    if isinstance(value, datetime):
        if value.year < 1700:
            from .services import solar_to_gregorian

            converted_date = solar_to_gregorian(value.date().isoformat())
            return datetime.combine(converted_date, value.timetz())
        return value

    if isinstance(value, date):
        if value.year < 1700:
            from .services import solar_to_gregorian

            converted_date = solar_to_gregorian(value.isoformat())
            return datetime.combine(converted_date, time.min)
        return datetime.combine(value, time.min)

    value = str(value).strip()
    date_part, separator, time_part = value.partition("T")

    if not separator:
        date_part, separator, time_part = value.partition(" ")

    try:
        year = int(date_part.split("-")[0])
    except Exception as exc:
        raise ValueError("Invalid receipt_date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]") from exc

    if year < 1700:
        from .services import solar_to_gregorian

        converted_date = solar_to_gregorian(date_part)
        if not separator:
            return datetime.combine(converted_date, time.min)
        try:
            return datetime.combine(converted_date, time.fromisoformat(time_part.replace("Z", "+00:00")))
        except ValueError as exc:
            raise ValueError("Invalid receipt_date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]") from exc

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid receipt_date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]") from exc


class FinancialCardBase(BaseModel):
    title: str = Field(..., min_length=1)
    card_number: str = Field(..., min_length=4, max_length=64)
    bank_name: Optional[str] = None
    account_owner_name: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True



class FinancialCardSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    is_active: Optional[bool] = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class FinancialCardCreate(FinancialCardBase):
    pass


class FinancialCardUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1)
    card_number: Optional[str] = Field(None, min_length=4, max_length=64)
    bank_name: Optional[str] = None
    account_owner_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class FinancialCardSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    card_number: str
    bank_name: Optional[str] = None
    account_owner_name: Optional[str] = None
    description: Optional[str] = None
    is_active: bool


class FinancialCardOut(FinancialCardSummaryOut):
    company_id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime


class FinancialCustomerBase(BaseModel):
    name: str = Field(..., min_length=1)
    phone_number1: str = Field(..., min_length=1)
    phone_number2: Optional[str] = None
    access_method: FinancialAccessMethod
    email: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone_number1", mode="before")
    @classmethod
    def normalize_required_phone_number1(cls, value):
        if value is None:
            raise ValueError("phone_number1 is required")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("phone_number1 is required")
            return value
        return value

    @field_validator("phone_number2", "email", "description", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value



class FinancialCustomerSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class FinancialCustomerCreate(FinancialCustomerBase):
    pass


class FinancialCustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    phone_number1: str
    phone_number2: Optional[str] = None
    access_method: FinancialAccessMethod
    email: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone_number1", mode="before")
    @classmethod
    def normalize_required_phone_number1(cls, value):
        if value is None:
            raise ValueError("phone_number1 is required")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("phone_number1 is required")
            return value
        return value

    @field_validator("phone_number2", "email", "description", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class FinancialCustomerSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone_number1: str
    phone_number2: Optional[str] = None
    access_method: FinancialAccessMethod
    email: Optional[str] = None
    description: Optional[str] = None


class FinancialCustomerOut(FinancialCustomerSummaryOut):
    company_id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime


class FinancialReceiptFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    media_address: str
    content_type: Optional[str] = None
    asset_id: Optional[int] = None
    created_at: datetime


class FinancialReceiptFileUploadUrlCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., gt=0)
    checksum: Optional[str] = None


class FinancialReceiptBase(BaseModel):
    description: str = Field(..., min_length=1)
    tracking_number: Optional[str] = None
    amount: Decimal = Field(..., gt=Decimal("0"))
    currency: FinancialCurrency = FinancialCurrency.TOMAN
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    direction: FinancialDirection
    counterparty_name: Optional[str] = None
    receipt_date: datetime
    credit_card_id: int
    customer_id: Optional[int] = None

    @validator("receipt_date", pre=True)
    def validate_receipt_date(cls, value):
        return normalize_receipt_date(value)


class FinancialReceiptCreate(FinancialReceiptBase):
    pass


class FinancialReceiptUpdate(BaseModel):
    description: Optional[str] = Field(None, min_length=1)
    tracking_number: Optional[str] = None
    amount: Optional[Decimal] = Field(None, gt=Decimal("0"))
    currency: Optional[FinancialCurrency] = None
    exchange_rate_to_base: Optional[Decimal] = Field(default=None, gt=Decimal("0"))
    direction: Optional[FinancialDirection] = None
    counterparty_name: Optional[str] = None
    receipt_date: Optional[datetime] = None
    credit_card_id: Optional[int] = None
    customer_id: Optional[int] = None

    @validator("receipt_date", pre=True)
    def validate_receipt_date(cls, value):
        return normalize_receipt_date(value)


class FinancialReceiptOut(BaseModel):
    id: int
    company_id: int
    owner_id: int
    description: str
    tracking_number: Optional[str] = None
    amount: Decimal
    currency: FinancialCurrency
    base_currency: FinancialCurrency
    exchange_rate_to_base: Decimal
    base_amount: Decimal
    exchange_rate_source: str
    direction: FinancialDirection
    counterparty_name: Optional[str] = None
    receipt_date: datetime
    credit_card: FinancialCardSummaryOut
    customer_id: Optional[int] = None
    customer: Optional[FinancialCustomerSummaryOut] = None
    embedding_status: Literal["available", "pending"]
    created_at: datetime
    updated_at: datetime
    files: List[FinancialReceiptFileOut] = Field(default_factory=list)



class FinancialReceiptCurrencySummaryOut(BaseModel):
    currency: FinancialCurrency
    input_amount: Decimal = Decimal("0")
    output_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    receipt_count: int = 0


class FinancialReceiptSummaryOut(BaseModel):
    base_currency: FinancialCurrency
    total_input_base: Decimal = Decimal("0")
    total_output_base: Decimal = Decimal("0")
    net_base: Decimal = Decimal("0")
    receipt_count: int = 0
    by_currency: List[FinancialReceiptCurrencySummaryOut] = Field(default_factory=list)

class FinancialReceiptBatchRequest(BaseModel):
    ids: List[int] = Field(default_factory=list)


class FinancialReceiptTextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class FinancialReceiptSemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)


class FinancialReceiptSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"
    limit: int = Field(default=10, ge=1, le=200)


class FinancialReceiptSemanticHit(BaseModel):
    receipt_id: int
    company_id: int
    description: str
    tracking_number: Optional[str] = None
    amount: Decimal
    currency: FinancialCurrency
    base_currency: FinancialCurrency
    exchange_rate_to_base: Decimal
    base_amount: Decimal
    exchange_rate_source: str
    direction: FinancialDirection
    counterparty_name: str
    receipt_date: datetime
    card_id: int
    card_title: str
    card_number: str
    owner_id: int
    createdAt: datetime
    match_source: Literal["semantic", "text", "text_fallback"]


class FinancialReceiptAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"
    receipt_ids: List[int] = Field(default_factory=list)


class FinancialReceiptAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_receipt_ids: List[int] = Field(default_factory=list)
    references: List[FinancialReceiptSemanticHit] = Field(default_factory=list)


class FinancialReceiptCommentLinkCreate(BaseModel):
    comment_id: int
    note: Optional[str] = None


class FinancialCreateCommentAndLinkRequest(BaseModel):
    payload: CommentCreate
    link_description: Optional[str] = None


class FinancialReceiptCommentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    receipt_id: int
    comment_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime


class FinancialReceiptCommentOut(BaseModel):
    id: int
    user_id: int
    title: str
    type: CommentType
    content: str
    created_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class FinancialReceiptLinkSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: Literal["keyword", "semantic", "vector", "hybrid"] = "hybrid"
    limit: int = Field(default=50, ge=1, le=200)
