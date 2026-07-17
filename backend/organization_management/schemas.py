from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _normalize_required_text(value, field_name: str) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError(f"{field_name} is required")

    return normalized


def _normalize_optional_text(value):
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


class OrganizationDepartmentCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    parent_department_id: Optional[int] = Field(None, gt=0)
    manager_user_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return _normalize_required_text(value, "code").upper()

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return _normalize_required_text(value, "name")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _normalize_optional_text(value)


class OrganizationDepartmentUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    parent_department_id: Optional[int] = Field(None, gt=0)
    manager_user_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        return _normalize_required_text(value, "code").upper()

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if value is None:
            return None
        return _normalize_required_text(value, "name")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _normalize_optional_text(value)


class OrganizationDepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    parent_department_id: Optional[int]
    manager_user_id: Optional[int]
    code: str
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationPositionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    department_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_manager: bool = False
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return _normalize_required_text(value, "code").upper()

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return _normalize_required_text(value, "title")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _normalize_optional_text(value)


class OrganizationPositionUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    department_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_manager: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        return _normalize_required_text(value, "code").upper()

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        if value is None:
            return None
        return _normalize_required_text(value, "title")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _normalize_optional_text(value)


class OrganizationPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    department_id: Optional[int]
    code: str
    title: str
    description: Optional[str]
    is_manager: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationUserAssignmentCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    department_id: int = Field(..., gt=0)
    position_id: Optional[int] = Field(None, gt=0)
    is_primary: bool = False
    is_active: bool = True
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError(
                "end_date cannot be earlier than start_date"
            )

        return self


class OrganizationUserAssignmentUpdate(BaseModel):
    user_id: Optional[int] = Field(None, gt=0)
    department_id: Optional[int] = Field(None, gt=0)
    position_id: Optional[int] = Field(None, gt=0)
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError(
                "end_date cannot be earlier than start_date"
            )

        return self


class OrganizationUserAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    user_id: int
    department_id: int
    position_id: Optional[int]
    is_primary: bool
    is_active: bool
    start_date: Optional[date]
    end_date: Optional[date]
    created_at: datetime
    updated_at: datetime
