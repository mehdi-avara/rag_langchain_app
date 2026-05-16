from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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

from financial_management.schemas import FinancialCardSummaryOut, FinancialReceiptCreate, FinancialReceiptOut
from financial_management.models import FinancialDirection
from model_management.models import ModelReceiptLink
from model_management.routes import receipts as receipt_routes
from model_management.schemas import ModelCreateReceiptAndLinkRequest


class QueryStub:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_row


class DummyDB:
    def __init__(self, links=None, existing_link=None):
        self.links = links or []
        self.existing_link = existing_link
        self.added = []

    def query(self, model):
        if model is ModelReceiptLink:
            return QueryStub(rows=self.links, first_row=self.existing_link)
        return QueryStub()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        return obj


def _receipt_out(receipt_id: int, amount: str, direction: str) -> FinancialReceiptOut:
    return FinancialReceiptOut(
        id=receipt_id,
        company_id=1,
        owner_id=3,
        description=f"Receipt {receipt_id}",
        tracking_number=None,
        amount=Decimal(amount),
        direction=direction,
        counterparty_name="Counterparty",
        receipt_date="1405-02-17",
        receipt_date_gregorian="2026-05-07",
        credit_card=FinancialCardSummaryOut(
            id=1,
            title="Main Card",
            card_number="6037991234567890",
            bank_name="Melli",
            account_owner_name="Mehdi",
            description=None,
            is_active=True,
        ),
        embedding_status="available",
        created_at=datetime(2026, 5, 7, 10, 0, 0),
        updated_at=datetime(2026, 5, 7, 10, 0, 0),
        files=[],
    )


def test_create_receipt_and_link_uses_financial_route_callables(monkeypatch):
    db = DummyDB()
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    monkeypatch.setattr(receipt_routes, "get_model_or_404", lambda *_args, **_kwargs: SimpleNamespace(id=8))
    monkeypatch.setattr(receipt_routes, "create_receipt", lambda **_kwargs: SimpleNamespace(id=51))
    monkeypatch.setattr(receipt_routes, "get_receipt", lambda **_kwargs: SimpleNamespace(id=51))
    monkeypatch.setattr(receipt_routes, "safe_embed_link_note", lambda *_args, **_kwargs: [0.5, 0.7])

    body = ModelCreateReceiptAndLinkRequest(
        payload=FinancialReceiptCreate(
            description="Fuel cost",
            tracking_number=None,
            amount=Decimal("150.00"),
            direction=FinancialDirection.OUTPUT,
            counterparty_name="Fuel Station",
            receipt_date="1405-02-17",
            credit_card_id=1,
        ),
        link_description="model-specific fuel cost",
    )

    link = receipt_routes.create_receipt_and_link(model_id=8, body=body, db=db, current_user=current_user)

    assert link.receipt_id == 51
    assert db.added[0].receipt_id == 51
    assert db.added[0].note_embedding == [0.5, 0.7]


def test_model_receipt_summary_aggregates_input_and_output(monkeypatch):
    links = [
        SimpleNamespace(receipt_id=11, note="a", created_at=datetime(2026, 5, 7, 10, 0, 0)),
        SimpleNamespace(receipt_id=12, note="b", created_at=datetime(2026, 5, 7, 11, 0, 0)),
    ]
    db = DummyDB(links=links)
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    monkeypatch.setattr(receipt_routes, "get_model_or_404", lambda *_args, **_kwargs: SimpleNamespace(id=8))
    monkeypatch.setattr(receipt_routes, "get_receipt_ids", lambda *_args, **_kwargs: [11, 12])
    monkeypatch.setattr(
        receipt_routes,
        "get_receipts_by_ids",
        lambda **_kwargs: [
            _receipt_out(11, "200.00", "input"),
            _receipt_out(12, "50.00", "output"),
        ],
    )

    summary = receipt_routes.get_model_receipt_summary(model_id=8, db=db, current_user=current_user)

    assert summary.total_receipts == 2
    assert summary.total_input_amount == Decimal("200.00")
    assert summary.total_output_amount == Decimal("50.00")
    assert summary.total_cost_amount == Decimal("50.00")
    assert summary.net_amount == Decimal("150.00")
