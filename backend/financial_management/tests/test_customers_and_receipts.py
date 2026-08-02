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

from db import seed_rbac
from financial_management.models import FinancialCard, FinancialCustomer, FinancialDirection
from financial_management.routes import customers as customer_routes
from financial_management.routes import receipts as receipt_routes
from financial_management.schemas import FinancialReceiptCreate


class QueryStub:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.first_row

    def all(self):
        return self.rows


class DummyDB:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.added = []
        self.deleted = []
        self._next_id = 1

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
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 16, 10, 0, 0)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at
        return obj


def current_user():
    return SimpleNamespace(id=3, company_id=8, role="user")


def build_card():
    card = FinancialCard(
        id=12,
        company_id=8,
        owner_id=3,
        title="Main Card",
        card_number="6037991234567890",
        bank_name="Melli",
        account_owner_name="Mehdi",
        description=None,
        is_active=True,
    )
    return card


def build_customer():
    customer = FinancialCustomer(
        id=5,
        company_id=8,
        owner_id=3,
        name="Acme Buyer",
        phone_number1="0912",
        phone_number2=None,
        access_method="whatsapp",
        email=None,
        description=None,
    )
    customer.created_at = datetime(2026, 5, 16, 9, 0, 0)
    customer.updated_at = datetime(2026, 5, 16, 9, 0, 0)
    return customer


def test_create_receipt_falls_back_to_customer_name(monkeypatch):
    db = DummyDB()
    card = build_card()
    customer = build_customer()

    monkeypatch.setattr(receipt_routes, "get_card_or_404", lambda *_args, **_kwargs: card)
    monkeypatch.setattr(receipt_routes, "get_customer_or_404", lambda *_args, **_kwargs: customer)
    monkeypatch.setattr(receipt_routes, "safe_embed_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        lambda **kwargs: {
        "amount": kwargs["amount"],
        "currency": "IRT",
        "base_currency": "IRT",
        "exchange_rate_to_base": Decimal("1"),
        "base_amount": kwargs["amount"],
        "exchange_rate_source": "system",
        "currency_id": 1,
        "base_currency_id": 1,
        "amount_base": kwargs["amount"],
        "exchange_rate_used": Decimal("1"),
    },
    )

    payload = FinancialReceiptCreate(
        description="Warehouse sale",
        tracking_number=None,
        amount=Decimal("200.00"),
        direction=FinancialDirection.INPUT,
        counterparty_name=None,
        receipt_date=datetime(2026, 5, 16, 15, 45, 0),
        credit_card_id=card.id,
        customer_id=customer.id,
    )

    result = receipt_routes.create_receipt(payload=payload, db=db, current_user=current_user())

    assert result.counterparty_name == "Acme Buyer"
    assert result.customer_id == 5
    assert result.customer.name == "Acme Buyer"
    assert result.receipt_date == datetime(2026, 5, 16, 15, 45, 0)


def test_delete_customer_blocks_when_receipt_exists(monkeypatch):
    customer = build_customer()

    class DeleteCustomerDB(DummyDB):
        def query(self, _model):
            return QueryStub(first_row=SimpleNamespace(id=99))

    db = DeleteCustomerDB()
    monkeypatch.setattr(customer_routes, "get_customer_or_404", lambda *_args, **_kwargs: customer)

    with pytest.raises(HTTPException) as exc:
        customer_routes.delete_customer(customer_id=5, db=db, current_user=current_user())

    assert exc.value.status_code == 409


def test_seed_rbac_includes_property_and_customer_permissions(monkeypatch):
    captured_permissions = []

    class FakeDB:
        def query(self, _model):
            return SimpleNamespace(
                filter=lambda *_args, **_kwargs: SimpleNamespace(
                    first=lambda: None
                )
            )

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    class FakeRole:
        def __init__(self, name):
            self.name = name
            self.permissions = []
            self.is_active = True

    fake_db = FakeDB()

    monkeypatch.setattr(seed_rbac, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        seed_rbac,
        "get_or_create_permission",
        lambda _db, name, resource, action, description=None: captured_permissions.append(name) or SimpleNamespace(
            name=name,
            resource=resource,
            action=action,
            description=description,
        ),
    )
    monkeypatch.setattr(seed_rbac, "get_or_create_role", lambda _db, name, description=None: FakeRole(name))

    seed_rbac.seed()

    assert "financial_management:customers:read" in captured_permissions
    assert "property_management:read" in captured_permissions
    assert "property_management:summary" in captured_permissions
    assert "supplier_management:read" in captured_permissions
