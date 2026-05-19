from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from buying_management.models import (  # noqa: E402
    BuyingCostAllocationMethod,
    BuyingCostType,
    BuyingProcess,
    BuyingProcessCost,
    BuyingProcessItem,
    BuyingProcessReceiptLink,
    BuyingProcessStatus,
)
from buying_management.routes import processes as process_routes  # noqa: E402
from buying_management.routes import summary as summary_routes  # noqa: E402
from buying_management.schemas import BuyingProcessCreate  # noqa: E402
from buying_management.services import (  # noqa: E402
    apply_buying_to_warehouse,
    calculate_buying_summary,
    ensure_process_can_apply_warehouse,
)
from financial_management.models import FinancialReceipt  # noqa: E402
from model_management.models import ManagedModel  # noqa: E402
from property_management.models import WarehouseItem  # noqa: E402


class QueryStub:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_row


class DummyDB:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.added = []
        self.deleted = []
        self.committed = False
        self._next_id = 100

    def query(self, model):
        return self.mapping.get(model, QueryStub())

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 18, 8, 0, 0)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at
        return obj


def current_user(company_id=3):
    return SimpleNamespace(id=7, company_id=company_id)


def item(item_id, quantity, unit_price_base, line_total_base=None):
    line_total_base = line_total_base if line_total_base is not None else Decimal(quantity) * Decimal(str(unit_price_base))
    return BuyingProcessItem(
        id=item_id,
        buying_process_id=1,
        model_id=1000 + item_id,
        color="black",
        quantity=quantity,
        unit_price=Decimal(str(unit_price_base)),
        currency="USD",
        exchange_rate_to_base=Decimal("1"),
        unit_price_base=Decimal(str(unit_price_base)),
        line_total=Decimal(quantity) * Decimal(str(unit_price_base)),
        line_total_base=Decimal(str(line_total_base)),
        allocated_cost_base=Decimal("0"),
        final_unit_cost_base=Decimal("0"),
    )


def cost(cost_id, amount_base, allocation_method, manual_allocations_json=None):
    return BuyingProcessCost(
        id=cost_id,
        buying_process_id=1,
        cost_type=BuyingCostType.TRANSPORTATION.value,
        amount=Decimal(str(amount_base)),
        currency="USD",
        exchange_rate_to_base=Decimal("1"),
        amount_base=Decimal(str(amount_base)),
        allocation_method=allocation_method,
        manual_allocations_json=manual_allocations_json,
    )


def process_with(items=None, costs=None, links=None, status=BuyingProcessStatus.DRAFT.value):
    process = BuyingProcess(
        id=1,
        company_id=3,
        owner_id=7,
        title="Order 1",
        supplier_name="Supplier",
        status=status,
        currency="USD",
        base_currency="USD",
        exchange_rate_to_base=Decimal("1"),
        purchase_date=datetime(2026, 5, 18, 8, 0, 0),
        affects_warehouse=True,
    )
    process.items = items or []
    process.costs = costs or []
    process.receipt_links = links or []
    return process


def summary_db(items=None, costs=None, receipts=None):
    return DummyDB(
        {
            BuyingProcessItem: QueryStub(rows=items or []),
            BuyingProcessCost: QueryStub(rows=costs or []),
            FinancialReceipt: QueryStub(rows=receipts or []),
        }
    )


def test_create_buying_process_sets_company_and_owner():
    db = DummyDB()
    payload = BuyingProcessCreate(
        title="May shipment",
        supplier_name="ACME",
        status="draft",
        currency="USD",
        base_currency="IRR",
        exchange_rate_to_base=Decimal("42000"),
        purchase_date=datetime(2026, 5, 18, 8, 0, 0),
        affects_warehouse=True,
    )

    created = process_routes.create_buying_process(payload=payload, db=db, current_user=current_user())

    assert created.company_id == 3
    assert created.owner_id == 7
    assert created.exchange_rate_to_base == Decimal("42000")


def test_by_quantity_allocation_and_summary_totals():
    first = item(1, 2, Decimal("100"))
    second = item(2, 3, Decimal("100"))
    extra = cost(1, Decimal("50"), BuyingCostAllocationMethod.BY_QUANTITY.value)
    process = process_with(items=[first, second], costs=[extra])

    summary = calculate_buying_summary(summary_db([first, second], [extra]), process)

    assert summary.product_total_base == Decimal("500")
    assert summary.extra_cost_total_base == Decimal("50")
    assert summary.grand_total_base == Decimal("550")
    assert summary.total_quantity == 5
    assert summary.items[0].allocated_cost_base == Decimal("20")
    assert summary.items[1].allocated_cost_base == Decimal("30")
    assert summary.items[0].final_unit_cost_base == Decimal("110")


def test_by_value_allocation():
    first = item(1, 1, Decimal("100"))
    second = item(2, 1, Decimal("300"))
    extra = cost(1, Decimal("40"), BuyingCostAllocationMethod.BY_VALUE.value)
    process = process_with(items=[first, second], costs=[extra])

    summary = calculate_buying_summary(summary_db([first, second], [extra]), process)

    assert summary.items[0].allocated_cost_base == Decimal("10")
    assert summary.items[1].allocated_cost_base == Decimal("30")


def test_manual_allocation_and_invalid_total():
    first = item(1, 1, Decimal("100"))
    second = item(2, 1, Decimal("200"))
    extra = cost(1, Decimal("30"), BuyingCostAllocationMethod.MANUAL.value, {"1": "10", "2": "20"})
    process = process_with(items=[first, second], costs=[extra])

    summary = calculate_buying_summary(summary_db([first, second], [extra]), process)

    assert summary.items[0].allocated_cost_base == Decimal("10")
    assert summary.items[1].allocated_cost_base == Decimal("20")

    bad_extra = cost(2, Decimal("30"), BuyingCostAllocationMethod.MANUAL.value, {"1": "10", "2": "19"})
    with pytest.raises(HTTPException) as exc:
        calculate_buying_summary(summary_db([first, second], [bad_extra]), process_with(items=[first, second], costs=[bad_extra]))
    assert exc.value.status_code == 422


def test_currency_snapshot_uses_stored_exchange_rate():
    bought_item = BuyingProcessItem(
        id=1,
        buying_process_id=1,
        model_id=10,
        color="white",
        quantity=2,
        unit_price=Decimal("10"),
        currency="CNY",
        exchange_rate_to_base=Decimal("2.5"),
        unit_price_base=Decimal("0"),
        line_total=Decimal("0"),
        line_total_base=Decimal("0"),
        allocated_cost_base=Decimal("0"),
        final_unit_cost_base=Decimal("0"),
    )
    process = process_with(items=[bought_item])

    summary = calculate_buying_summary(summary_db([bought_item], []), process)

    assert bought_item.unit_price_base == Decimal("25.0")
    assert summary.product_total_base == Decimal("50.0")


def test_receipt_total_and_unmatched_amount():
    bought_item = item(1, 1, Decimal("100"))
    linked = BuyingProcessReceiptLink(buying_process_id=1, receipt_id=55, linked_by_user_id=7, purpose="product_payment")
    receipt = FinancialReceipt(id=55, company_id=3, owner_id=7, amount=Decimal("120"))
    process = process_with(items=[bought_item], links=[linked])

    summary = calculate_buying_summary(summary_db([bought_item], [], [receipt]), process)

    assert summary.receipt_total_base == Decimal("120")
    assert summary.unmatched_receipt_amount_base == Decimal("20")


def test_apply_warehouse_creates_item_and_blocks_double_apply():
    bought_item = item(1, 4, Decimal("25"))
    process = process_with(items=[bought_item])
    db = DummyDB(
        {
            BuyingProcessItem: QueryStub(rows=[bought_item]),
            BuyingProcessCost: QueryStub(rows=[]),
            FinancialReceipt: QueryStub(rows=[]),
            WarehouseItem: QueryStub(first_row=None),
        }
    )

    apply_buying_to_warehouse(db, process, current_user())

    warehouse_items = [obj for obj in db.added if isinstance(obj, WarehouseItem)]
    assert warehouse_items[0].count == 4
    assert warehouse_items[0].unit_cost == Decimal("25")
    assert process.warehouse_applied_at is not None

    with pytest.raises(HTTPException) as exc:
        ensure_process_can_apply_warehouse(process)
    assert exc.value.status_code == 409


def test_apply_warehouse_weighted_average():
    bought_item = item(1, 2, Decimal("20"))
    process = process_with(items=[bought_item])
    existing = WarehouseItem(
        id=9,
        company_id=3,
        owner_id=7,
        model_id=bought_item.model_id,
        color=bought_item.color,
        count=2,
        unit_cost=Decimal("10"),
    )
    db = DummyDB(
        {
            BuyingProcessItem: QueryStub(rows=[bought_item]),
            BuyingProcessCost: QueryStub(rows=[]),
            FinancialReceipt: QueryStub(rows=[]),
            WarehouseItem: QueryStub(first_row=existing),
        }
    )

    apply_buying_to_warehouse(db, process, current_user())

    assert existing.count == 4
    assert existing.unit_cost == Decimal("15")


def test_delete_applied_process_is_blocked():
    process = process_with(items=[item(1, 1, Decimal("10"))])
    process.warehouse_applied_at = datetime(2026, 5, 18, 9, 0, 0)
    db = DummyDB({BuyingProcess: QueryStub(first_row=process)})

    with pytest.raises(HTTPException) as exc:
        process_routes.delete_buying_process(process_id=process.id, db=db, current_user=current_user())

    assert exc.value.status_code == 409


def test_close_and_cancel_process():
    process = process_with(items=[item(1, 1, Decimal("10"))])
    db = DummyDB({BuyingProcess: QueryStub(first_row=process)})

    closed = summary_routes.close_buying_process(process_id=process.id, db=db, current_user=current_user())
    assert closed.status == BuyingProcessStatus.CLOSED.value

    process.warehouse_applied_at = None
    cancelled = summary_routes.cancel_buying_process(process_id=process.id, db=db, current_user=current_user())
    assert cancelled.status == BuyingProcessStatus.CANCELLED.value


def test_reject_model_from_another_company_and_receipt_from_another_company():
    db = DummyDB(
        {
            ManagedModel: QueryStub(first_row=None),
            FinancialReceipt: QueryStub(first_row=None),
        }
    )
    from buying_management.services import get_model_for_company_or_404, get_receipt_for_company_or_404

    with pytest.raises(HTTPException) as model_exc:
        get_model_for_company_or_404(db, 1, 3)
    assert model_exc.value.status_code == 404

    with pytest.raises(HTTPException) as receipt_exc:
        get_receipt_for_company_or_404(db, 1, 3)
    assert receipt_exc.value.status_code == 404
