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

from financial_management.models import FinancialDirection
from property_management.routes import properties as property_routes
from property_management.routes import warehouse as warehouse_routes
from property_management.schemas import OwnedPropertyCreate, WarehouseCountAdjustRequest
from property_management.services import build_net_worth_summary


class QueryStub:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
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

    def query(self, model):
        return self.mapping.get(model, QueryStub())

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 16, 12, 0, 0)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at
        return obj


def current_user():
    return SimpleNamespace(id=7, company_id=3, role="user")


def test_create_property_sets_company_and_owner():
    db = DummyDB()
    created = property_routes.create_property(
        payload=OwnedPropertyCreate(
            category="car",
            title="Company Car",
            purchase_cost=Decimal("10000.00"),
            current_estimated_value=Decimal("12000.00"),
            description="Fleet vehicle",
        ),
        db=db,
        current_user=current_user(),
    )

    assert db.added[0].company_id == 3
    assert db.added[0].owner_id == 7
    assert created.title == "Company Car"


def test_decrease_warehouse_count_blocks_negative(monkeypatch):
    item = SimpleNamespace(count=2)
    monkeypatch.setattr(warehouse_routes, "get_warehouse_item_or_404", lambda *_args, **_kwargs: item)

    with pytest.raises(HTTPException) as exc:
        warehouse_routes.decrease_warehouse_count(
            item_id=1,
            payload=WarehouseCountAdjustRequest(amount=3),
            db=DummyDB(),
            current_user=current_user(),
        )

    assert exc.value.status_code == 409


def test_delete_warehouse_item_requires_zero_count(monkeypatch):
    item = SimpleNamespace(count=1)
    monkeypatch.setattr(warehouse_routes, "get_warehouse_item_or_404", lambda *_args, **_kwargs: item)

    with pytest.raises(HTTPException) as exc:
        warehouse_routes.delete_warehouse_item(
            item_id=1,
            db=DummyDB(),
            current_user=current_user(),
        )

    assert exc.value.status_code == 409


def test_net_worth_summary_uses_current_values_and_cash_balance():
    warehouse_items = [
        SimpleNamespace(unit_cost=Decimal("10.00"), unit_current_value=Decimal("15.00"), count=4),
        SimpleNamespace(unit_cost=None, unit_current_value=Decimal("20.00"), count=1),
    ]
    properties = [
        SimpleNamespace(purchase_cost=Decimal("100.00"), current_estimated_value=Decimal("140.00")),
        SimpleNamespace(purchase_cost=None, current_estimated_value=Decimal("60.00")),
    ]
    receipts = [
        SimpleNamespace(amount=Decimal("300.00"), direction=FinancialDirection.INPUT),
        SimpleNamespace(amount=Decimal("50.00"), direction=FinancialDirection.OUTPUT),
    ]

    from property_management.models import OwnedProperty, WarehouseItem
    from financial_management.models import FinancialReceipt

    db = DummyDB(
        {
            WarehouseItem: QueryStub(rows=warehouse_items),
            OwnedProperty: QueryStub(rows=properties),
            FinancialReceipt: QueryStub(rows=receipts),
        }
    )

    summary = build_net_worth_summary(db, current_user())

    assert summary.warehouse_cost_total == Decimal("40.00")
    assert summary.warehouse_current_value_total == Decimal("80.00")
    assert summary.property_cost_total == Decimal("100.00")
    assert summary.property_current_value_total == Decimal("200.00")
    assert summary.cash_balance == Decimal("250.00")
    assert summary.net_worth == Decimal("530.00")
