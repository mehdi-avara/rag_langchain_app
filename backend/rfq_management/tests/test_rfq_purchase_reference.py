from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import rfq_management.services as rfq_services


def _rfq_with_winner(response_items):
    winner = SimpleNamespace(
        id=20,
        supplier_id=7,
        supplier_name="Vendor A",
        is_winner=True,
        delivery_days=14,
        items=response_items,
    )

    return SimpleNamespace(
        id=3,
        mr_id=9,
        rfq_number="RFQ-2026-0003",
        title="Critical spare parts",
        description="Quote comparison complete",
        items=[
            SimpleNamespace(
                id=100,
                item_id=501,
                item_code="SP-001",
                item_name="Seal",
                unit_code="PCS",
                quantity=Decimal("4"),
            ),
            SimpleNamespace(
                id=101,
                item_id=502,
                item_code="SP-002",
                item_name="Bearing",
                unit_code="PCS",
                quantity=Decimal("2"),
            ),
        ],
        responses=[winner],
    )


def _quote_item(rfq_item_id):
    return SimpleNamespace(
        rfq_item_id=rfq_item_id,
        unit_price=Decimal("10"),
        currency_id=1,
        unit_price_base=Decimal("10"),
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
        notes=None,
    )


def test_winning_quotation_reference_requires_every_rfq_item(monkeypatch):
    rfq = _rfq_with_winner([_quote_item(100)])

    monkeypatch.setattr(
        rfq_services,
        "get_rfq_or_404",
        lambda db, current_user, rfq_id: rfq,
    )

    with pytest.raises(HTTPException) as exc_info:
        rfq_services.get_winning_quotation_reference_for_purchase(
            db=None,
            current_user=SimpleNamespace(company_id=1),
            rfq_id=3,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "RFQ_WINNING_QUOTATION_INCOMPLETE"


def test_winning_quotation_reference_returns_uniform_complete_quote(monkeypatch):
    rfq = _rfq_with_winner([_quote_item(100), _quote_item(101)])

    monkeypatch.setattr(
        rfq_services,
        "get_rfq_or_404",
        lambda db, current_user, rfq_id: rfq,
    )

    result = rfq_services.get_winning_quotation_reference_for_purchase(
        db=None,
        current_user=SimpleNamespace(company_id=1),
        rfq_id=3,
    )

    assert result["rfq_id"] == 3
    assert result["mr_id"] == 9
    assert result["winning_quotation_response_id"] == 20
    assert result["supplier_id"] == 7
    assert len(result["items"]) == 2
    assert result["items"][0]["item_id"] == 501

def test_select_winner_rejects_incomplete_quote_before_closing_rfq(monkeypatch):
    response = SimpleNamespace(
        id=20,
        supplier_id=7,
        supplier_name="Vendor A",
        is_winner=False,
        selected_by_user_id=None,
        selected_at=None,
        delivery_days=14,
        items=[_quote_item(100)],
    )

    rfq = SimpleNamespace(
        id=3,
        status="sent",
        items=[
            SimpleNamespace(id=100, item_id=501),
            SimpleNamespace(id=101, item_id=502),
        ],
        responses=[response],
    )

    class RecordingSession:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    db = RecordingSession()

    monkeypatch.setattr(
        rfq_services,
        "get_rfq_or_404",
        lambda db, current_user, rfq_id: rfq,
    )
    monkeypatch.setattr(
        rfq_services,
        "_get_response_or_404",
        lambda db, rfq, quotation_response_id: response,
    )

    with pytest.raises(HTTPException) as exc_info:
        rfq_services.select_winning_quotation(
            db=db,
            current_user=SimpleNamespace(company_id=1, id=2),
            rfq_id=3,
            quotation_response_id=20,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "RFQ_WINNING_QUOTATION_INCOMPLETE"
    assert response.is_winner is False
    assert rfq.status == "sent"
    assert db.commits == 0
