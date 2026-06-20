from __future__ import annotations

import asyncio
import io
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

from financial_management.models import FinancialCard, FinancialDirection, FinancialReceipt
from financial_management.routes import comments as comment_routes
from financial_management.routes import ask as ask_routes
from financial_management.routes import files as file_routes
from financial_management.routes import receipts as receipt_routes
from financial_management.search.service import search_receipt_hits
from financial_management.schemas import (
    FinancialReceiptCommentLinkCreate,
    FinancialReceiptAskRequest,
    FinancialReceiptBatchRequest,
    FinancialReceiptCreate,
    FinancialReceiptUpdate,
    FinancialReceiptSemanticHit,
)
from financial_management.services import (
    build_receipt_context,
    gregorian_to_solar,
    mask_card_number,
    parse_receipt_citations,
    safe_embed_text,
    solar_to_gregorian,
)


class DummyDB:
    def __init__(self):
        self.added = []
        self.deleted = []
        self._next_id = 1

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 5, 10, 0, 0)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at
        return obj

    def delete(self, obj):
        self.deleted.append(obj)

    def query(self, _model):
        return QueryProxy()


class QueryProxy:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_row


class DummyUpload:
    def __init__(self, filename: str, data: bytes, content_type: str = "image/png"):
        self.filename = filename
        self._data = data
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def build_card() -> FinancialCard:
    card = FinancialCard(
        id=9,
        owner_id=3,
        company_id=1,
        title="Main Card",
        card_number="6037991234567890",
        bank_name="Melli",
        account_owner_name="Mehdi",
        description="Primary card",
        is_active=True,
    )
    card.created_at = datetime(2026, 5, 5, 9, 0, 0)
    card.updated_at = datetime(2026, 5, 5, 9, 0, 0)
    return card


def build_receipt() -> FinancialReceipt:
    card = build_card()
    receipt = FinancialReceipt(
        id=11,
        owner_id=3,
        company_id=1,
        credit_card_id=card.id,
        description="Paid for machine repair",
        description_embedding=[0.1, 0.2],
        tracking_number=None,
        amount=Decimal("1250000.00"),
        currency="IRT",
        base_currency="IRT",
        exchange_rate_to_base=Decimal("1"),
        base_amount=Decimal("1250000.00"),
        exchange_rate_source="system",
        direction=FinancialDirection.OUTPUT,
        counterparty_name="Repair Center",
        receipt_date=datetime(2026, 5, 5, 8, 15, 0),
    )
    receipt.created_at = datetime(2026, 5, 5, 10, 30, 0)
    receipt.updated_at = datetime(2026, 5, 5, 10, 30, 0)
    receipt.credit_card = card
    receipt.files = []
    return receipt


def test_solar_date_conversion_round_trip():
    assert solar_to_gregorian("1405-01-01").isoformat() == "2026-03-21"
    assert gregorian_to_solar(solar_to_gregorian("1405-02-15")) == "1405-02-15"


def test_mask_card_number_and_receipt_citations():
    assert mask_card_number("6037 9912 3456 7890") == "6037991234567890"
    assert parse_receipt_citations("a [receipt:5] b [receipt:5] [receipt:7]") == [5, 7]


def test_safe_embed_text_returns_none_when_embedding_fails(monkeypatch):
    monkeypatch.setattr("financial_management.services.generate_embeddings_for_chunks", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    assert safe_embed_text("test") is None


def test_search_receipt_hits_falls_back_to_text(monkeypatch):
    receipt = build_receipt()
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    monkeypatch.setattr("financial_management.search.service.ensure_receipt_embeddings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "financial_management.search.service.search_financial_receipt_hits_semantic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("embedding disabled")),
    )
    monkeypatch.setattr(
        "financial_management.search.service.search_financial_receipts_text",
        lambda *_args, **_kwargs: [receipt],
    )

    hits = search_receipt_hits(
        db=object(),
        current_user=current_user,
        query_text="repair",
        mode="vector",
        receipt_ids=[receipt.id],
        limit=5,
    )

    assert len(hits) == 1
    assert hits[0].receipt_id == receipt.id
    assert hits[0].match_source == "text_fallback"


def test_create_receipt_keeps_tracking_number_nullable(monkeypatch):
    db = DummyDB()
    current_user = SimpleNamespace(id=3, role="user", company_id=1)
    card = build_card()

    monkeypatch.setattr(receipt_routes, "get_card_or_404", lambda *_args, **_kwargs: card)
    monkeypatch.setattr(receipt_routes, "safe_embed_text", lambda *_args, **_kwargs: None)

    payload = FinancialReceiptCreate(
        description="Paid electricity bill",
        tracking_number=None,
        amount=Decimal("450000.50"),
        direction=FinancialDirection.OUTPUT,
        counterparty_name="Power Company",
        receipt_date="1405-02-15T14:45:30",
        credit_card_id=card.id,
    )

    response = receipt_routes.create_receipt(payload=payload, db=db, current_user=current_user)

    assert response.tracking_number is None
    assert response.embedding_status == "pending"
    assert response.receipt_date.isoformat() == "2026-05-05T14:45:30"


def test_receipt_update_accepts_datetime_local_string():
    payload = FinancialReceiptUpdate(receipt_date="2026-05-16T09:30")

    assert payload.receipt_date == datetime(2026, 5, 16, 9, 30, 0)


def test_build_receipt_context_contains_key_fields():
    receipt = build_receipt()
    hit = SimpleNamespace(
        receipt_id=receipt.id,
        receipt_date="1405-02-15",
        direction=receipt.direction,
        amount=receipt.amount,
        counterparty_name=receipt.counterparty_name,
        tracking_number=receipt.tracking_number,
        card_title=receipt.credit_card.title,
        card_number=mask_card_number(receipt.credit_card.card_number),
        description=receipt.description,
    )

    context = build_receipt_context([hit])
    assert "[receipt:11]" in context
    assert "tracking=-" in context
    assert "Main Card" in context


def test_ask_receipts_returns_receipt_citations(monkeypatch):
    hit = FinancialReceiptSemanticHit(
        receipt_id=11,
        description="Paid for machine repair",
        tracking_number=None,
        amount=Decimal("1250000.00"),
        currency="IRT",
        base_currency="IRT",
        exchange_rate_to_base=Decimal("1"),
        base_amount=Decimal("1250000.00"),
        exchange_rate_source="system",
        direction=FinancialDirection.OUTPUT,
        counterparty_name="Repair Center",
        receipt_date=datetime(2026, 5, 5, 8, 15, 0),
        card_id=9,
        card_title="Main Card",
        card_number="************7890",
        owner_id=3,
        company_id=1,
        createdAt=datetime(2026, 5, 5, 10, 30, 0),
        match_source="text_fallback",
    )

    monkeypatch.setattr(ask_routes, "search_receipts", lambda **_kwargs: [hit])
    monkeypatch.setattr(ask_routes, "get_receipt_or_404", lambda *_args, **_kwargs: build_receipt())
    monkeypatch.setattr(ask_routes, "generate_receipt_answer", lambda *_args, **_kwargs: asyncio.sleep(0, result="done [receipt:11]"))

    result = asyncio.run(
        ask_routes.ask_receipts(
            payload=FinancialReceiptAskRequest(question="What did I pay for?", mode="vector", receipt_ids=[11]),
            db=object(),
            current_user=SimpleNamespace(id=3, role="user", company_id=1),
        )
    )

    assert result.citations == [11]
    assert result.used_receipt_ids == [11]
    assert result.references[0].receipt_id == 11


def test_add_receipt_file_writes_under_financial_management(tmp_path, monkeypatch):
    db = DummyDB()
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    monkeypatch.setattr(file_routes, "get_receipt_or_404", lambda *_args, **_kwargs: build_receipt())
    monkeypatch.setattr(file_routes.settings, "files_dir", str(tmp_path))

    result = asyncio.run(
        file_routes.add_receipt_file(
            receipt_id=11,
            file=DummyUpload("receipt.png", b"binary-image-data"),
            db=db,
            current_user=current_user,
        )
    )

    assert result.file_name == "receipt.png"
    assert "financial_management/receipts/11" in result.media_address
    assert io.open(result.media_address, "rb").read() == b"binary-image-data"


def test_get_receipts_by_ids_preserves_requested_order(monkeypatch):
    current_user = SimpleNamespace(id=3, role="user", company_id=1)
    receipt_a = build_receipt()
    receipt_b = build_receipt()
    receipt_a.id = 22
    receipt_b.id = 11

    class ReceiptDB(DummyDB):
        def query(self, _model):
            return QueryProxy(rows=[receipt_a, receipt_b])

    result = receipt_routes.get_receipts_by_ids(
        payload=FinancialReceiptBatchRequest(ids=[11, 22]),
        db=ReceiptDB(),
        current_user=current_user,
    )

    assert [item.id for item in result] == [11, 22]


def test_link_receipt_comment_stores_note_embedding(monkeypatch):
    db = DummyDB()
    current_user = SimpleNamespace(id=3, role="user", company_id=1)
    comment = SimpleNamespace(id=91, user_id=3)

    class CommentDB(DummyDB):
        def query(self, model):
            if model.__name__ == "Comment":
                return QueryProxy(first_row=comment)
            return QueryProxy(first_row=None)

    monkeypatch.setattr(comment_routes, "get_receipt_or_404", lambda *_args, **_kwargs: build_receipt())
    monkeypatch.setattr(comment_routes, "safe_embed_text", lambda *_args, **_kwargs: [0.1, 0.3])

    link = comment_routes.link_comment(
        receipt_id=11,
        payload=FinancialReceiptCommentLinkCreate(comment_id=91, note="repair note"),
        db=CommentDB(),
        current_user=current_user,
    )

    assert link.comment_id == 91


def test_get_receipt_or_404_allows_same_company_receipt_owned_by_another_user():
    from financial_management.services import get_receipt_or_404

    receipt = build_receipt()
    receipt.owner_id = 99
    receipt.company_id = 1

    class ReceiptDB(DummyDB):
        def query(self, _model):
            return QueryProxy(first_row=receipt)

    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    result = get_receipt_or_404(ReceiptDB(), receipt.id, current_user)

    assert result is receipt


def test_get_receipts_by_ids_filters_by_company_not_owner():
    current_user = SimpleNamespace(id=3, role="user", company_id=1)

    receipt_a = build_receipt()
    receipt_a.id = 11
    receipt_a.owner_id = 99
    receipt_a.company_id = 1

    receipt_b = build_receipt()
    receipt_b.id = 22
    receipt_b.owner_id = 3
    receipt_b.company_id = 1

    class ReceiptDB(DummyDB):
        def query(self, _model):
            return QueryProxy(rows=[receipt_a, receipt_b])

    result = receipt_routes.get_receipts_by_ids(
        payload=FinancialReceiptBatchRequest(ids=[11, 22]),
        db=ReceiptDB(),
        current_user=current_user,
    )

    assert [item.id for item in result] == [11, 22]
    assert [item.owner_id for item in result] == [99, 3]


def test_search_receipt_hits_passes_company_scope_to_repositories(monkeypatch):
    receipt = build_receipt()
    current_user = SimpleNamespace(id=3, role="user", company_id=77)
    calls = []

    monkeypatch.setattr(
        "financial_management.search.service.ensure_receipt_embeddings",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "financial_management.search.service.search_financial_receipt_hits_semantic",
        lambda *_args, **_kwargs: [],
    )

    def fake_text_search(**kwargs):
        calls.append(kwargs)
        return [receipt]

    monkeypatch.setattr(
        "financial_management.search.service.search_financial_receipts_text",
        fake_text_search,
    )

    hits = search_receipt_hits(
        db=object(),
        current_user=current_user,
        query_text="repair",
        mode="keyword",
        receipt_ids=[11, 11, 22],
        limit=5,
    )

    assert len(hits) == 1
    assert calls[0]["company_id"] == 77
    assert calls[0]["receipt_ids"] == [11, 22]
