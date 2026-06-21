from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models.user import User
from financial_management.models import FinancialDirection, FinancialReceipt
from model_management.services import require_company
from warehouse_management.services import inventory_value_summary_for_company

from .models import OwnedProperty
from .schemas import NetWorthSummaryOut, OwnedPropertyOut


def decimal_or_zero(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def get_owned_property_or_404(
    db: Session,
    property_id: int,
    current_user: User,
) -> OwnedProperty:
    owned_property = (
        db.query(OwnedProperty)
        .filter(
            OwnedProperty.id == property_id,
            OwnedProperty.company_id == require_company(current_user),
        )
        .first()
    )

    if not owned_property:
        raise HTTPException(status_code=404, detail="Property not found")

    return owned_property


def owned_property_to_out(
    owned_property: OwnedProperty,
) -> OwnedPropertyOut:
    return OwnedPropertyOut(
        id=owned_property.id,
        company_id=owned_property.company_id,
        owner_id=owned_property.owner_id,
        category=owned_property.category,
        title=owned_property.title,
        purchase_cost=(
            Decimal(str(owned_property.purchase_cost))
            if owned_property.purchase_cost is not None
            else None
        ),
        current_estimated_value=(
            Decimal(str(owned_property.current_estimated_value))
            if owned_property.current_estimated_value is not None
            else None
        ),
        description=owned_property.description,
        created_at=owned_property.created_at,
        updated_at=owned_property.updated_at,
    )


def build_net_worth_summary(
    db: Session,
    current_user: User,
) -> NetWorthSummaryOut:
    company_id = require_company(current_user)

    inventory = inventory_value_summary_for_company(
        db=db,
        company_id=company_id,
    )
    warehouse_value = inventory["value_total"]

    owned_properties = (
        db.query(OwnedProperty)
        .filter(OwnedProperty.company_id == company_id)
        .all()
    )

    property_cost_total = sum(
        (
            decimal_or_zero(owned_property.purchase_cost)
            for owned_property in owned_properties
        ),
        Decimal("0"),
    )

    property_current_value_total = sum(
        (
            decimal_or_zero(owned_property.current_estimated_value)
            for owned_property in owned_properties
        ),
        Decimal("0"),
    )

    receipts = (
        db.query(FinancialReceipt)
        .filter(FinancialReceipt.company_id == company_id)
        .all()
    )

    total_input = Decimal("0")
    total_output = Decimal("0")

    for receipt in receipts:
        amount = Decimal(str(receipt.amount))

        if receipt.direction == FinancialDirection.INPUT:
            total_input += amount
        else:
            total_output += amount

    cash_balance = total_input - total_output

    return NetWorthSummaryOut(
        warehouse_cost_total=warehouse_value,
        warehouse_current_value_total=warehouse_value,
        property_cost_total=property_cost_total,
        property_current_value_total=property_current_value_total,
        cash_balance=cash_balance,
        net_worth=(
            warehouse_value
            + property_current_value_total
            + cash_balance
        ),
    )


__all__ = [
    "build_net_worth_summary",
    "get_owned_property_or_404",
    "owned_property_to_out",
    "require_company",
]
