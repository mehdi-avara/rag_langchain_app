from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

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

from financial_management.models import FinancialDirection, FinancialReceipt
from property_management.models import OwnedProperty
from property_management.routes import properties as property_routes
from property_management.schemas import OwnedPropertyCreate
import property_management.services as property_services


class QueryStub:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_row


class DummyDB:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.added = []

    def query(self, model):
        return self.mapping.get(model, QueryStub())

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1

        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 6, 21, 12, 0, 0)

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


def test_create_property_accepts_trillion_value():
    db = DummyDB()

    created = property_routes.create_property(
        payload=OwnedPropertyCreate(
            category="house",
            title="Large Property",
            purchase_cost=Decimal("1000000000000.00"),
            current_estimated_value=Decimal("1000000000000.00"),
        ),
        db=db,
        current_user=current_user(),
    )

    assert created.purchase_cost == Decimal("1000000000000.00")
    assert created.current_estimated_value == Decimal("1000000000000.00")


def test_property_schema_rejects_value_beyond_supported_precision():
    with pytest.raises(ValidationError) as exc:
        OwnedPropertyCreate(
            category="house",
            title="Too Large Property",
            current_estimated_value=Decimal("10000000000000000000000.01"),
        )

    assert any(error["type"] == "decimal_max_digits" for error in exc.value.errors())


def test_property_model_uses_wide_numeric_columns():
    assert OwnedProperty.__table__.c.purchase_cost.type.precision == 24
    assert OwnedProperty.__table__.c.purchase_cost.type.scale == 2
    assert OwnedProperty.__table__.c.current_estimated_value.type.precision == 24
    assert OwnedProperty.__table__.c.current_estimated_value.type.scale == 2


def test_net_worth_summary_uses_inventory_and_cash_balance(monkeypatch):
    properties = [
        SimpleNamespace(
            purchase_cost=Decimal("100.00"),
            current_estimated_value=Decimal("140.00"),
        ),
        SimpleNamespace(
            purchase_cost=None,
            current_estimated_value=Decimal("60.00"),
        ),
    ]

    receipts = [
        SimpleNamespace(
            amount=Decimal("300.00"),
            direction=FinancialDirection.INPUT,
        ),
        SimpleNamespace(
            amount=Decimal("50.00"),
            direction=FinancialDirection.OUTPUT,
        ),
    ]

    monkeypatch.setattr(
        property_services,
        "inventory_value_summary_for_company",
        lambda db, company_id: {
            "quantity_total": Decimal("5"),
            "value_total": Decimal("80.00"),
        },
    )

    db = DummyDB(
        {
            OwnedProperty: QueryStub(rows=properties),
            FinancialReceipt: QueryStub(rows=receipts),
        }
    )

    summary = property_services.build_net_worth_summary(
        db,
        current_user(),
    )

    assert summary.warehouse_cost_total == Decimal("80.00")
    assert summary.warehouse_current_value_total == Decimal("80.00")
    assert summary.property_cost_total == Decimal("100.00")
    assert summary.property_current_value_total == Decimal("200.00")
    assert summary.cash_balance == Decimal("250.00")
    assert summary.net_worth == Decimal("530.00")
