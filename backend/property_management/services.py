from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models import User
from financial_management.models import FinancialDirection, FinancialReceipt
from model_management.services import get_model_or_404, require_company

from .models import OwnedProperty, WarehouseItem
from .schemas import NetWorthSummaryOut, OwnedPropertyOut, WarehouseItemOut, WarehouseModelSummaryOut


def decimal_or_zero(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def get_warehouse_item_or_404(db: Session, item_id: int, current_user: User) -> WarehouseItem:
    item = (
        db.query(WarehouseItem)
        .filter(
            WarehouseItem.id == item_id,
            WarehouseItem.company_id == require_company(current_user),
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Warehouse item not found")
    return item


def get_owned_property_or_404(db: Session, property_id: int, current_user: User) -> OwnedProperty:
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


def warehouse_item_to_out(item: WarehouseItem) -> WarehouseItemOut:
    unit_cost = decimal_or_zero(item.unit_cost)
    unit_current_value = decimal_or_zero(item.unit_current_value)

    return WarehouseItemOut(
        id=item.id,
        company_id=item.company_id,
        owner_id=item.owner_id,
        model=WarehouseModelSummaryOut(
            id=item.model.id,
            manufacturer=item.model.manufacturer,
            model=item.model.model,
            type=item.model.type,
        ),
        color=item.color,
        count=item.count,
        description=item.description,
        unit_cost=Decimal(str(item.unit_cost)) if item.unit_cost is not None else None,
        unit_current_value=Decimal(str(item.unit_current_value)) if item.unit_current_value is not None else None,
        total_cost=unit_cost * item.count,
        total_current_value=unit_current_value * item.count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def owned_property_to_out(owned_property: OwnedProperty) -> OwnedPropertyOut:
    return OwnedPropertyOut(
        id=owned_property.id,
        company_id=owned_property.company_id,
        owner_id=owned_property.owner_id,
        category=owned_property.category,
        title=owned_property.title,
        purchase_cost=Decimal(str(owned_property.purchase_cost)) if owned_property.purchase_cost is not None else None,
        current_estimated_value=Decimal(str(owned_property.current_estimated_value))
        if owned_property.current_estimated_value is not None else None,
        description=owned_property.description,
        created_at=owned_property.created_at,
        updated_at=owned_property.updated_at,
    )


def build_net_worth_summary(db: Session, current_user: User) -> NetWorthSummaryOut:
    company_id = require_company(current_user)

    warehouse_items = db.query(WarehouseItem).filter(WarehouseItem.company_id == company_id).all()
    warehouse_cost_total = sum((decimal_or_zero(item.unit_cost) * item.count for item in warehouse_items), Decimal("0"))
    warehouse_current_value_total = sum(
        (decimal_or_zero(item.unit_current_value) * item.count for item in warehouse_items),
        Decimal("0"),
    )

    owned_properties = db.query(OwnedProperty).filter(OwnedProperty.company_id == company_id).all()
    property_cost_total = sum((decimal_or_zero(item.purchase_cost) for item in owned_properties), Decimal("0"))
    property_current_value_total = sum(
        (decimal_or_zero(item.current_estimated_value) for item in owned_properties),
        Decimal("0"),
    )

    receipts = db.query(FinancialReceipt).filter(FinancialReceipt.company_id == company_id).all()
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
        warehouse_cost_total=warehouse_cost_total,
        warehouse_current_value_total=warehouse_current_value_total,
        property_cost_total=property_cost_total,
        property_current_value_total=property_current_value_total,
        cash_balance=cash_balance,
        net_worth=warehouse_current_value_total + property_current_value_total + cash_balance,
    )


__all__ = [
    "build_net_worth_summary",
    "get_model_or_404",
    "get_owned_property_or_404",
    "get_warehouse_item_or_404",
    "owned_property_to_out",
    "require_company",
    "warehouse_item_to_out",
]
