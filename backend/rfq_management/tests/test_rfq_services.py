from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import rfq_management.services as rfq_services
from rfq_management.models import (
    QuotationResponseItem,
    RFQStatus,
)
from rfq_management.schemas import (
    QuotationResponseItemCreate,
    RequestForQuotationCreate,
)
from rfq_management.services import get_rfq_transition_target


def test_rfq_transition_targets_follow_workflow():
    assert (
        get_rfq_transition_target(RFQStatus.DRAFT.value, "send")
        == RFQStatus.SENT.value
    )
    assert (
        get_rfq_transition_target(RFQStatus.SENT.value, "close")
        == RFQStatus.CLOSED.value
    )
    assert (
        get_rfq_transition_target(RFQStatus.SENT.value, "cancel")
        == RFQStatus.CANCELLED.value
    )


def test_invalid_rfq_transition_returns_none():
    assert get_rfq_transition_target(RFQStatus.CLOSED.value, "send") is None
    assert get_rfq_transition_target(RFQStatus.CANCELLED.value, "close") is None


def test_standalone_rfq_requires_items():
    with pytest.raises(ValidationError):
        RequestForQuotationCreate(
            title="Blank RFQ",
            deadline_date="2026-07-01",
        )


def test_mr_rfq_cannot_receive_manual_items():
    with pytest.raises(ValidationError):
        RequestForQuotationCreate(
            mr_id=1,
            title="RFQ from MR",
            deadline_date="2026-07-01",
            items=[
                {
                    "item_id": 1,
                    "quantity": Decimal("1"),
                }
            ],
        )


def test_quotation_item_accepts_complete_money_pattern():
    line = QuotationResponseItemCreate(
        rfq_item_id=1,
        unit_price=Decimal("12.5"),
        currency_id=1,
        unit_price_base=Decimal("12.5"),
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
    )

    assert line.unit_price == Decimal("12.5")
    assert line.currency_id == 1


class _EmptyQuery:
    def filter(self, *args):
        return self

    def first(self):
        return None


class _RecordingSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def query(self, *args):
        return _EmptyQuery()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = len(self.added)

    def commit(self):
        self.commits += 1


def test_quote_response_is_attached_to_loaded_rfq_collections(monkeypatch):
    db = _RecordingSession()
    rfq = SimpleNamespace(id=11, responses=[])
    rfq_supplier = SimpleNamespace(response_status="pending")

    monkeypatch.setattr(rfq_services, "get_rfq_or_404", lambda *args, **kwargs: rfq)
    monkeypatch.setattr(rfq_services, "_assert_sent", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        rfq_services,
        "_resolve_supplier_reference",
        lambda *args, **kwargs: {"id": 7, "code": "SUP-7", "name": "Supplier 7"},
    )
    monkeypatch.setattr(
        rfq_services,
        "_get_rfq_supplier_or_404",
        lambda *args, **kwargs: rfq_supplier,
    )
    monkeypatch.setattr(
        rfq_services,
        "_build_response_item",
        lambda **kwargs: QuotationResponseItem(
            quotation_response_id=kwargs["quotation_response_id"],
            rfq_item_id=3,
            unit_price=Decimal("10"),
            currency_id=1,
            unit_price_base=Decimal("10"),
            base_currency_id=1,
            exchange_rate_used=Decimal("1"),
        ),
    )
    monkeypatch.setattr(
        rfq_services,
        "_get_response_or_404",
        lambda db, rfq, quotation_response_id: rfq.responses[0],
    )

    response = rfq_services.create_quotation_response(
        db=db,
        current_user=SimpleNamespace(),
        rfq_id=rfq.id,
        data={
            "supplier_id": 7,
            "items": [{"rfq_item_id": 3}],
        },
    )

    assert rfq.responses == [response]
    assert len(response.items) == 1
    assert response.items[0].rfq_item_id == 3
    assert rfq_supplier.response_status == "responded"



def _make_transition_rfq(status, items=None, suppliers=None):
    return SimpleNamespace(
        id=77,
        status=status,
        items=[] if items is None else items,
        suppliers=[] if suppliers is None else suppliers,
    )


def _patch_rfq_lookup(monkeypatch, rfq):
    monkeypatch.setattr(
        rfq_services,
        "get_rfq_or_404",
        lambda *args, **kwargs: rfq,
    )


def test_rfq_transition_target_allows_draft_cancellation():
    assert (
        get_rfq_transition_target(RFQStatus.DRAFT.value, "cancel")
        == RFQStatus.CANCELLED.value
    )


@pytest.mark.parametrize(
    ("current_status", "action"),
    [
        (RFQStatus.DRAFT.value, "close"),
        (RFQStatus.SENT.value, "send"),
        (RFQStatus.CLOSED.value, "send"),
        (RFQStatus.CLOSED.value, "close"),
        (RFQStatus.CLOSED.value, "cancel"),
        (RFQStatus.CANCELLED.value, "send"),
        (RFQStatus.CANCELLED.value, "close"),
        (RFQStatus.CANCELLED.value, "cancel"),
    ],
)
def test_rfq_transition_target_rejects_invalid_workflow_paths(
    current_status,
    action,
):
    assert get_rfq_transition_target(current_status, action) is None


def test_transition_rfq_send_marks_suppliers_and_commits(monkeypatch):
    supplier = SimpleNamespace(
        sent_at=None,
        response_status="pending",
    )
    rfq = _make_transition_rfq(
        status=RFQStatus.DRAFT.value,
        items=[SimpleNamespace(id=1)],
        suppliers=[supplier],
    )
    db = _RecordingSession()

    _patch_rfq_lookup(monkeypatch, rfq)

    result = rfq_services.transition_rfq(
        db=db,
        current_user=SimpleNamespace(),
        rfq_id=rfq.id,
        action=" send ",
    )

    assert result is rfq
    assert rfq.status == RFQStatus.SENT.value
    assert supplier.sent_at is not None
    assert supplier.response_status == "pending"
    assert db.commits == 1


@pytest.mark.parametrize(
    ("items", "suppliers", "expected_code"),
    [
        ([], [SimpleNamespace()], "RFQ_HAS_NO_ITEMS"),
        ([SimpleNamespace(id=1)], [], "RFQ_HAS_NO_SUPPLIERS"),
    ],
)
def test_transition_rfq_send_requires_items_and_suppliers(
    monkeypatch,
    items,
    suppliers,
    expected_code,
):
    rfq = _make_transition_rfq(
        status=RFQStatus.DRAFT.value,
        items=items,
        suppliers=suppliers,
    )
    db = _RecordingSession()

    _patch_rfq_lookup(monkeypatch, rfq)

    with pytest.raises(HTTPException) as exc_info:
        rfq_services.transition_rfq(
            db=db,
            current_user=SimpleNamespace(),
            rfq_id=rfq.id,
            action="send",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == expected_code
    assert rfq.status == RFQStatus.DRAFT.value
    assert db.commits == 0


@pytest.mark.parametrize(
    ("start_status", "action", "expected_status"),
    [
        (
            RFQStatus.SENT.value,
            "close",
            RFQStatus.CLOSED.value,
        ),
        (
            RFQStatus.DRAFT.value,
            "cancel",
            RFQStatus.CANCELLED.value,
        ),
        (
            RFQStatus.SENT.value,
            "cancel",
            RFQStatus.CANCELLED.value,
        ),
    ],
)
def test_transition_rfq_applies_valid_non_send_actions(
    monkeypatch,
    start_status,
    action,
    expected_status,
):
    rfq = _make_transition_rfq(status=start_status)
    db = _RecordingSession()

    _patch_rfq_lookup(monkeypatch, rfq)

    result = rfq_services.transition_rfq(
        db=db,
        current_user=SimpleNamespace(),
        rfq_id=rfq.id,
        action=action,
    )

    assert result is rfq
    assert rfq.status == expected_status
    assert db.commits == 1


@pytest.mark.parametrize(
    ("start_status", "action"),
    [
        (RFQStatus.CLOSED.value, "cancel"),
        (RFQStatus.CANCELLED.value, "close"),
    ],
)
def test_transition_rfq_rejects_terminal_state_actions(
    monkeypatch,
    start_status,
    action,
):
    rfq = _make_transition_rfq(status=start_status)
    db = _RecordingSession()

    _patch_rfq_lookup(monkeypatch, rfq)

    with pytest.raises(HTTPException) as exc_info:
        rfq_services.transition_rfq(
            db=db,
            current_user=SimpleNamespace(),
            rfq_id=rfq.id,
            action=action,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "RFQ_INVALID_STATUS_TRANSITION"
    assert rfq.status == start_status
    assert db.commits == 0
