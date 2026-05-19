from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from Models import User
from financial_management.models import FinancialReceipt
from model_management.models import ManagedModel
from property_management.models import WarehouseItem

from .models import (
    BuyingCostAllocationMethod,
    BuyingProcess,
    BuyingProcessCost,
    BuyingProcessItem,
    BuyingProcessReceiptLink,
    BuyingProcessStatus,
)
from .schemas import BuyingProcessItemCostSummaryOut, BuyingProcessSummaryOut


def decimal_or_zero(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def require_company(current_user: User) -> int:
    if current_user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")
    return current_user.company_id


def get_buying_process_or_404(db: Session, process_id: int, current_user: User) -> BuyingProcess:
    process = (
        db.query(BuyingProcess)
        .options(
            joinedload(BuyingProcess.items),
            joinedload(BuyingProcess.costs),
            joinedload(BuyingProcess.receipt_links),
        )
        .filter(
            BuyingProcess.id == process_id,
            BuyingProcess.company_id == require_company(current_user),
        )
        .first()
    )
    if not process:
        raise HTTPException(status_code=404, detail="Buying process not found")
    return process


def get_buying_item_or_404(
    db: Session,
    process: BuyingProcess,
    item_id: int,
) -> BuyingProcessItem:
    item = (
        db.query(BuyingProcessItem)
        .filter(
            BuyingProcessItem.id == item_id,
            BuyingProcessItem.buying_process_id == process.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Buying item not found")
    return item


def get_buying_cost_or_404(
    db: Session,
    process: BuyingProcess,
    cost_id: int,
) -> BuyingProcessCost:
    cost = (
        db.query(BuyingProcessCost)
        .filter(
            BuyingProcessCost.id == cost_id,
            BuyingProcessCost.buying_process_id == process.id,
        )
        .first()
    )
    if not cost:
        raise HTTPException(status_code=404, detail="Buying cost not found")
    return cost


def get_model_for_company_or_404(db: Session, model_id: int, company_id: int) -> ManagedModel:
    model = (
        db.query(ManagedModel)
        .filter(
            ManagedModel.id == model_id,
            ManagedModel.company_id == company_id,
        )
        .first()
    )
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


def get_receipt_for_company_or_404(db: Session, receipt_id: int, company_id: int) -> FinancialReceipt:
    receipt = (
        db.query(FinancialReceipt)
        .filter(
            FinancialReceipt.id == receipt_id,
            FinancialReceipt.company_id == company_id,
        )
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Financial receipt not found")
    return receipt


def ensure_process_editable(process: BuyingProcess) -> None:
    if process.warehouse_applied_at is not None:
        raise HTTPException(status_code=409, detail="Cannot edit after warehouse was applied")


def ensure_process_can_apply_warehouse(process: BuyingProcess) -> None:
    if process.warehouse_applied_at is not None:
        raise HTTPException(status_code=409, detail="Warehouse already applied")
    if not process.affects_warehouse:
        raise HTTPException(status_code=409, detail="Buying process does not affect warehouse")
    if process.status == BuyingProcessStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="Cannot apply cancelled process to warehouse")
    if not process.items:
        raise HTTPException(status_code=409, detail="Cannot apply a buying process with no items")


def compute_item_amounts(item: BuyingProcessItem) -> None:
    item.unit_price_base = decimal_or_zero(item.unit_price) * decimal_or_zero(item.exchange_rate_to_base)
    item.line_total = Decimal(item.quantity) * decimal_or_zero(item.unit_price)
    item.line_total_base = Decimal(item.quantity) * decimal_or_zero(item.unit_price_base)
    item.final_unit_cost_base = (
        (decimal_or_zero(item.line_total_base) + decimal_or_zero(item.allocated_cost_base)) / Decimal(item.quantity)
        if item.quantity
        else Decimal("0")
    )


def compute_cost_amount(cost: BuyingProcessCost) -> None:
    cost.amount_base = decimal_or_zero(cost.amount) * decimal_or_zero(cost.exchange_rate_to_base)


def normalize_manual_allocations(value: dict | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {str(item_id): str(Decimal(str(amount))) for item_id, amount in value.items()}


def _manual_allocation_total(cost: BuyingProcessCost) -> Decimal:
    if not cost.manual_allocations_json:
        return Decimal("0")
    return sum((Decimal(str(amount)) for amount in cost.manual_allocations_json.values()), Decimal("0"))


def validate_manual_allocation(cost: BuyingProcessCost, items: Iterable[BuyingProcessItem]) -> None:
    if cost.allocation_method != BuyingCostAllocationMethod.MANUAL.value:
        return

    item_ids = {item.id for item in items if item.id is not None}
    allocations = cost.manual_allocations_json or {}
    unknown_ids = [item_id for item_id in allocations if int(item_id) not in item_ids]
    if unknown_ids:
        raise HTTPException(status_code=422, detail="Manual allocation references an unknown buying item")

    allocation_total = _manual_allocation_total(cost)
    if allocation_total != decimal_or_zero(cost.amount_base):
        raise HTTPException(status_code=422, detail="Manual allocation total must match cost amount")


def allocate_costs(
    process: BuyingProcess,
    items: list[BuyingProcessItem],
    costs: list[BuyingProcessCost],
) -> dict[int, Decimal]:
    allocations = {item.id: Decimal("0") for item in items}
    product_total_base = sum((decimal_or_zero(item.line_total_base) for item in items), Decimal("0"))
    total_quantity = sum((item.quantity for item in items), 0)

    for cost in costs:
        amount_base = decimal_or_zero(cost.amount_base)
        method = cost.allocation_method

        if method == BuyingCostAllocationMethod.BY_QUANTITY.value:
            if total_quantity <= 0:
                raise HTTPException(status_code=422, detail="by_quantity allocation requires total quantity greater than zero")
            for item in items:
                allocations[item.id] += amount_base * Decimal(item.quantity) / Decimal(total_quantity)

        elif method == BuyingCostAllocationMethod.BY_VALUE.value:
            if product_total_base <= 0:
                raise HTTPException(status_code=422, detail="by_value allocation requires product total greater than zero")
            for item in items:
                allocations[item.id] += amount_base * decimal_or_zero(item.line_total_base) / product_total_base

        elif method == BuyingCostAllocationMethod.MANUAL.value:
            validate_manual_allocation(cost, items)
            for item_id, amount in (cost.manual_allocations_json or {}).items():
                allocations[int(item_id)] += Decimal(str(amount))

        else:
            raise HTTPException(status_code=422, detail="Invalid allocation method")

    return allocations


def calculate_buying_summary(db: Session, process: BuyingProcess) -> BuyingProcessSummaryOut:
    items = (
        db.query(BuyingProcessItem)
        .filter(BuyingProcessItem.buying_process_id == process.id)
        .order_by(BuyingProcessItem.id.asc())
        .all()
    )
    costs = (
        db.query(BuyingProcessCost)
        .filter(BuyingProcessCost.buying_process_id == process.id)
        .order_by(BuyingProcessCost.id.asc())
        .all()
    )

    for item in items:
        compute_item_amounts(item)
    for cost in costs:
        compute_cost_amount(cost)

    allocations = allocate_costs(process, items, costs) if items else {}

    item_summaries: list[BuyingProcessItemCostSummaryOut] = []
    for item in items:
        allocated_cost = allocations.get(item.id, Decimal("0"))
        item.allocated_cost_base = allocated_cost
        item.final_unit_cost_base = (
            (decimal_or_zero(item.line_total_base) + allocated_cost) / Decimal(item.quantity)
            if item.quantity
            else Decimal("0")
        )
        item_summaries.append(
            BuyingProcessItemCostSummaryOut(
                item_id=item.id,
                model_id=item.model_id,
                color=item.color,
                quantity=item.quantity,
                line_total_base=decimal_or_zero(item.line_total_base),
                allocated_cost_base=decimal_or_zero(item.allocated_cost_base),
                final_unit_cost_base=decimal_or_zero(item.final_unit_cost_base),
            )
        )

    product_total_base = sum((decimal_or_zero(item.line_total_base) for item in items), Decimal("0"))
    extra_cost_total_base = sum((decimal_or_zero(cost.amount_base) for cost in costs), Decimal("0"))
    grand_total_base = product_total_base + extra_cost_total_base
    receipt_ids = [link.receipt_id for link in process.receipt_links]
    receipt_total_base = Decimal("0")
    if receipt_ids:
        receipt_total_base = sum(
            (
                decimal_or_zero(receipt.amount)
                for receipt in db.query(FinancialReceipt)
                .filter(FinancialReceipt.id.in_(receipt_ids), FinancialReceipt.company_id == process.company_id)
                .all()
            ),
            Decimal("0"),
        )

    return BuyingProcessSummaryOut(
        process_id=process.id,
        product_total_base=product_total_base,
        extra_cost_total_base=extra_cost_total_base,
        grand_total_base=grand_total_base,
        receipt_total_base=receipt_total_base,
        unmatched_receipt_amount_base=receipt_total_base - grand_total_base,
        total_quantity=sum((item.quantity for item in items), 0),
        items=item_summaries,
    )


def apply_buying_to_warehouse(db: Session, process: BuyingProcess, current_user: User) -> BuyingProcessSummaryOut:
    ensure_process_can_apply_warehouse(process)
    summary = calculate_buying_summary(db, process)

    item_costs = {item.item_id: item.final_unit_cost_base for item in summary.items}
    for item in process.items:
        warehouse_item = (
            db.query(WarehouseItem)
            .filter(
                WarehouseItem.company_id == process.company_id,
                WarehouseItem.model_id == item.model_id,
                WarehouseItem.color == item.color,
            )
            .first()
        )
        new_quantity = item.quantity
        new_unit_cost = item_costs[item.id]

        if warehouse_item is None:
            warehouse_item = WarehouseItem(
                company_id=process.company_id,
                owner_id=current_user.id,
                model_id=item.model_id,
                color=item.color,
                count=new_quantity,
                unit_cost=new_unit_cost,
            )
            db.add(warehouse_item)
            continue

        old_count = warehouse_item.count
        old_unit_cost = decimal_or_zero(warehouse_item.unit_cost)
        total_count = old_count + new_quantity
        warehouse_item.unit_cost = (
            ((Decimal(old_count) * old_unit_cost) + (Decimal(new_quantity) * new_unit_cost)) / Decimal(total_count)
            if total_count
            else Decimal("0")
        )
        warehouse_item.count = total_count

    process.warehouse_applied_at = datetime.utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Warehouse item conflict while applying buying process") from exc

    db.refresh(process)
    return summary


def receipt_link_exists(db: Session, process_id: int, receipt_id: int) -> bool:
    return (
        db.query(BuyingProcessReceiptLink)
        .filter(
            BuyingProcessReceiptLink.buying_process_id == process_id,
            BuyingProcessReceiptLink.receipt_id == receipt_id,
        )
        .first()
        is not None
    )
