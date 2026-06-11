from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from financial_management.models import FinancialCurrency


class CompanySettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    base_currency: FinancialCurrency
    is_active: bool


class CompanySettingsUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    base_currency: Optional[FinancialCurrency] = None
