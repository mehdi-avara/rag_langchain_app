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

from financial_management.schemas import FinancialCardSummaryOut, FinancialReceiptOut
from tag_management.models import TagReceiptLink
from tag_management.routes import receipts as receipt_routes


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
    def __init__(self, links=None):
        self.links = links or []

    def query(self, model):
        if model is TagReceiptLink:
            return QueryStub(rows=self.links)
        return QueryStub()


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


def test_tag_receipt_summary_aggregates_costs(monkeypatch):
    links = [
        SimpleNamespace(receipt_id=21, note="a", created_at=datetime(2026, 5, 7, 10, 0, 0)),
        SimpleNamespace(receipt_id=22, note="b", created_at=datetime(2026, 5, 7, 11, 0, 0)),
    ]
    db = DummyDB(links=links)
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    monkeypatch.setattr(receipt_routes, "get_tag_or_404", lambda *_args, **_kwargs: SimpleNamespace(id=5))
    monkeypatch.setattr(receipt_routes, "get_receipt_ids", lambda *_args, **_kwargs: [21, 22])
    monkeypatch.setattr(
        receipt_routes,
        "get_receipts_by_ids",
        lambda **_kwargs: [
            _receipt_out(21, "80.00", "output"),
            _receipt_out(22, "20.00", "input"),
        ],
    )

    summary = receipt_routes.get_tag_receipt_summary(tag_id=5, db=db, current_user=current_user)

    assert summary.total_receipts == 2
    assert summary.total_input_amount == Decimal("20.00")
    assert summary.total_output_amount == Decimal("80.00")
    assert summary.total_cost_amount == Decimal("80.00")
    assert summary.net_amount == Decimal("-60.00")
