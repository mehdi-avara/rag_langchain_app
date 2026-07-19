from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import purchase_management.services as purchase_services
from purchase_management.models import (
    PurchaseApprovalStatus,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
    PurchasePhaseStatus,
)


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self._next_id = 1

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        return value


def test_approval_orders_purchase_order_and_draft_phases(monkeypatch):
    purchase_order = SimpleNamespace(
        approval_status=PurchaseApprovalStatus.PENDING.value,
        status=PurchaseOrderStatus.DRAFT.value,
        approved_by_user_id=None,
        phases=[
            SimpleNamespace(status=PurchasePhaseStatus.DRAFT.value),
            SimpleNamespace(status=PurchasePhaseStatus.SHIPPED.value),
        ],
    )
    db = FakeSession()
    user = SimpleNamespace(id=11)

    monkeypatch.setattr(
        purchase_services,
        "get_po_or_404",
        lambda db, po_id, user: purchase_order,
    )

    result = purchase_services.process_approval(
        db=db,
        user=user,
        po_id=7,
        action="approve",
        note=None,
    )

    assert result is purchase_order
    assert purchase_order.approval_status == PurchaseApprovalStatus.APPROVED.value
    assert purchase_order.status == PurchaseOrderStatus.ORDERED.value
    assert purchase_order.approved_by_user_id == 11
    assert purchase_order.phases[0].status == PurchasePhaseStatus.ORDERED.value
    assert purchase_order.phases[1].status == PurchasePhaseStatus.SHIPPED.value
    assert db.commits == 1


def test_create_purchase_order_from_rfq_creates_traceable_lines(monkeypatch):
    db = FakeSession()
    user = SimpleNamespace(id=11, company_id=3)

    source = {
        "rfq_id": 8,
        "rfq_number": "RFQ-2026-0008",
        "mr_id": None,
        "title": "Pump spare parts",
        "description": "Approved supplier quotation",
        "supplier_id": 14,
        "supplier_name": "Vendor A",
        "winning_quotation_response_id": 22,
        "currency_id": 1,
        "base_currency_id": 1,
        "exchange_rate_used": Decimal("1"),
        "delivery_days": 10,
        "items": [
            {
                "item_id": 101,
                "item_code": "BRG-001",
                "item_name": "Bearing",
                "unit_id": 7,
                "unit_code": "PCS",
                "quantity": Decimal("2"),
                "specifications": "Original bearing specification",
                "unit_price": Decimal("12.5"),
                "currency_id": 1,
                "unit_price_base": Decimal("12.5"),
                "base_currency_id": 1,
                "exchange_rate_used": Decimal("1"),
                "notes": "Original manufacturer",
            }
        ],
    }

    monkeypatch.setattr(
        purchase_services,
        "_get_purchase_order_for_rfq",
        lambda db, user, rfq_id: None,
    )
    monkeypatch.setattr(
        purchase_services,
        "_get_winning_quotation_reference_for_purchase",
        lambda db, user, rfq_id: source,
    )
    monkeypatch.setattr(
        purchase_services,
        "_next_reference_number",
        lambda db, company_id: "PO-2026-0001",
    )
    monkeypatch.setattr(
        purchase_services,
        "get_po_or_404",
        lambda db, po_id, user: db.added[0],
    )

    purchase_order = purchase_services.create_purchase_order_from_rfq(
        db=db,
        user=user,
        rfq_id=8,
    )

    purchase_phase = next(
        value
        for value in db.added
        if isinstance(value, PurchasePhase)
    )
    purchase_line = next(
        value
        for value in db.added
        if isinstance(value, PurchaseOrderLine)
    )
    allocation = next(
        value
        for value in db.added
        if isinstance(
            value,
            PurchasePhaseAllocation,
        )
    )

    assert purchase_order.rfq_id == 8
    assert (
        purchase_order.source_material_requisition_id
        is None
    )
    assert (
        purchase_order.winning_quotation_response_id
        == 22
    )
    assert purchase_order.supplier_id == 14
    assert purchase_order.status == (
        PurchaseOrderStatus.DRAFT.value
    )

    assert purchase_phase.purchase_order_id == (
        purchase_order.id
    )
    assert purchase_phase.status == (
        PurchasePhaseStatus.DRAFT.value
    )

    assert purchase_line.purchase_order_id == (
        purchase_order.id
    )
    assert purchase_line.line_number == 1
    assert purchase_line.item_id == 101
    assert purchase_line.unit_id == 7
    assert purchase_line.ordered_quantity == (
        Decimal("2")
    )
    assert purchase_line.unit_price == (
        Decimal("12.5")
    )
    assert purchase_line.unit_price_base == (
        Decimal("12.5")
    )
    assert purchase_line.line_description == (
        "Original bearing specification"
    )

    assert allocation.phase_id == purchase_phase.id
    assert allocation.purchase_order_line_id == (
        purchase_line.id
    )
    assert allocation.allocated_quantity == (
        Decimal("2")
    )

    assert db.commits == 1


def test_create_purchase_order_from_rfq_marks_linked_requisition(monkeypatch):
    db = FakeSession()
    user = SimpleNamespace(id=11, company_id=3)
    calls = []

    source = {
        "rfq_id": 8,
        "rfq_number": "RFQ-2026-0008",
        "mr_id": 31,
        "title": "Pump spare parts",
        "description": None,
        "supplier_id": 14,
        "supplier_name": "Vendor A",
        "winning_quotation_response_id": 22,
        "currency_id": 1,
        "base_currency_id": 1,
        "exchange_rate_used": Decimal("1"),
        "delivery_days": None,
        "items": [
            {
                "item_id": 101,
                "item_code": "BRG-001",
                "item_name": "Bearing",
                "unit_id": 7,
                "unit_code": "PCS",
                "quantity": Decimal("2"),
                "specifications": "Original bearing specification",
                "unit_price": Decimal("12.5"),
                "currency_id": 1,
                "unit_price_base": Decimal("12.5"),
                "base_currency_id": 1,
                "exchange_rate_used": Decimal("1"),
                "notes": None,
            }
        ],
    }

    monkeypatch.setattr(
        purchase_services,
        "_get_purchase_order_for_rfq",
        lambda db, user, rfq_id: None,
    )
    monkeypatch.setattr(
        purchase_services,
        "_get_winning_quotation_reference_for_purchase",
        lambda db, user, rfq_id: source,
    )
    monkeypatch.setattr(
        purchase_services,
        "_next_reference_number",
        lambda db, company_id: "PO-2026-0001",
    )
    monkeypatch.setattr(
        purchase_services,
        "_mark_requisition_ordered_from_purchase_order",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        purchase_services,
        "get_po_or_404",
        lambda db, po_id, user: db.added[0],
    )

    purchase_services.create_purchase_order_from_rfq(
        db=db,
        user=user,
        rfq_id=8,
    )

    assert len(calls) == 1
    assert calls[0]["requisition_id"] == 31
    assert calls[0]["purchase_order_reference"] == "PO-2026-0001"


def test_create_purchase_order_from_rfq_rejects_duplicate_link(monkeypatch):
    db = FakeSession()
    user = SimpleNamespace(id=11, company_id=3)

    monkeypatch.setattr(
        purchase_services,
        "_get_purchase_order_for_rfq",
        lambda db, user, rfq_id: SimpleNamespace(id=42),
    )

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.create_purchase_order_from_rfq(
            db=db,
            user=user,
            rfq_id=8,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PURCHASE_ORDER_RFQ_ALREADY_LINKED"



def _purchase_order(
    status=PurchaseOrderStatus.DRAFT.value,
    approval_status=PurchaseApprovalStatus.DRAFT.value,
    phases=None,
    lines=None,
):
    default_phase = SimpleNamespace(
        id=21,
        status=PurchasePhaseStatus.DRAFT.value,
    )
    default_line = SimpleNamespace(
        line_number=1,
        ordered_quantity=Decimal("2"),
        currency_id=1,
        exchange_rate_used=Decimal("1"),
        allocations=[
            SimpleNamespace(
                phase_id=21,
                allocated_quantity=Decimal("2"),
            )
        ],
    )

    return SimpleNamespace(
        supplier_id=14,
        currency_id=1,
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
        status=status,
        approval_status=approval_status,
        approved_by_user_id=None,
        phases=(
            [default_phase]
            if phases is None
            else phases
        ),
        lines=(
            [default_line]
            if lines is None
            else lines
        ),
    )


def _patch_purchase_order_lookup(monkeypatch, purchase_order):
    monkeypatch.setattr(
        purchase_services,
        "get_po_or_404",
        lambda db, po_id, user: purchase_order,
    )


def test_submit_moves_purchase_order_to_pending(monkeypatch):
    purchase_order = _purchase_order()
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    result = purchase_services.process_approval(
        db=db,
        user=user,
        po_id=7,
        action="submit",
        note="Submit for approval",
    )

    assert result is purchase_order
    assert purchase_order.status == PurchaseOrderStatus.DRAFT.value
    assert purchase_order.approval_status == PurchaseApprovalStatus.PENDING.value
    assert purchase_order.approved_by_user_id is None
    assert db.commits == 1


def test_reject_moves_pending_purchase_order_to_rejected(monkeypatch):
    purchase_order = _purchase_order(
        approval_status=PurchaseApprovalStatus.PENDING.value,
    )
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    result = purchase_services.process_approval(
        db=db,
        user=user,
        po_id=7,
        action="reject",
        note="Rejected in workflow test",
    )

    assert result is purchase_order
    assert purchase_order.status == PurchaseOrderStatus.DRAFT.value
    assert purchase_order.approval_status == PurchaseApprovalStatus.REJECTED.value
    assert purchase_order.approved_by_user_id is None
    assert db.commits == 1


@pytest.mark.parametrize(
    ("approval_status", "action", "expected_message"),
    [
        (
            PurchaseApprovalStatus.DRAFT.value,
            "approve",
            "Only pending orders can be approved",
        ),
        (
            PurchaseApprovalStatus.DRAFT.value,
            "reject",
            "Only pending orders can be rejected",
        ),
        (
            PurchaseApprovalStatus.PENDING.value,
            "submit",
            "Only draft orders can be submitted for approval",
        ),
        (
            PurchaseApprovalStatus.REJECTED.value,
            "approve",
            "Only pending orders can be approved",
        ),
    ],
)
def test_invalid_purchase_order_approval_transitions_are_rejected(
    monkeypatch,
    approval_status,
    action,
    expected_message,
):
    purchase_order = _purchase_order(approval_status=approval_status)
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.process_approval(
            db=db,
            user=user,
            po_id=7,
            action=action,
            note=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == expected_message
    assert purchase_order.approval_status == approval_status
    assert purchase_order.status == PurchaseOrderStatus.DRAFT.value
    assert db.commits == 0


def test_unknown_purchase_order_approval_action_is_rejected(monkeypatch):
    purchase_order = _purchase_order()
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.process_approval(
            db=db,
            user=user,
            po_id=7,
            action="ordered",
            note=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Unknown approval action: ordered"
    assert purchase_order.status == PurchaseOrderStatus.DRAFT.value
    assert purchase_order.approval_status == PurchaseApprovalStatus.DRAFT.value
    assert db.commits == 0


def test_cancel_purchase_order_marks_status_cancelled(monkeypatch):
    purchase_order = _purchase_order()
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    result = purchase_services.cancel_purchase_order(
        db=db,
        user=user,
        po_id=7,
    )

    assert result is purchase_order
    assert purchase_order.status == PurchaseOrderStatus.CANCELLED.value
    assert purchase_order.approval_status == PurchaseApprovalStatus.DRAFT.value
    assert db.commits == 1


def test_cancelled_purchase_order_cannot_be_updated(monkeypatch):
    purchase_order = _purchase_order(
        status=PurchaseOrderStatus.CANCELLED.value,
    )
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(monkeypatch, purchase_order)

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.update_purchase_order(
            db=db,
            user=user,
            po_id=7,
            description="Must not be saved",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Cannot edit a cancelled purchase order"
    assert db.commits == 0



def test_submit_rejects_empty_legacy_purchase_order(monkeypatch):
    purchase_order = _purchase_order(
        phases=[],
        lines=[],
    )
    db = FakeSession()
    user = SimpleNamespace(id=11)

    _patch_purchase_order_lookup(
        monkeypatch,
        purchase_order,
    )

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.process_approval(
            db=db,
            user=user,
            po_id=7,
            action="submit",
            note=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "PURCHASE_ORDER_INVALID_STRUCTURE"
    )
    assert db.commits == 0



def test_create_purchase_order_from_rfq_rejects_missing_unit(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )

    source = {
        "rfq_id": 8,
        "rfq_number": "RFQ-2026-0008",
        "mr_id": None,
        "title": "Pump spare parts",
        "description": None,
        "supplier_id": 14,
        "supplier_name": "Vendor A",
        "winning_quotation_response_id": 22,
        "currency_id": 1,
        "base_currency_id": 1,
        "exchange_rate_used": Decimal("1"),
        "delivery_days": None,
        "items": [
            {
                "item_id": 101,
                "item_code": "BRG-001",
                "item_name": "Bearing",
                "unit_id": None,
                "unit_code": "PCS",
                "quantity": Decimal("2"),
                "specifications": None,
                "unit_price": Decimal("12.5"),
                "currency_id": 1,
                "unit_price_base": Decimal("12.5"),
                "base_currency_id": 1,
                "exchange_rate_used": Decimal("1"),
                "notes": None,
            }
        ],
    }

    monkeypatch.setattr(
        purchase_services,
        "_get_purchase_order_for_rfq",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        purchase_services,
        "_get_winning_quotation_reference_for_purchase",
        lambda **kwargs: source,
    )

    with pytest.raises(HTTPException) as exc_info:
        purchase_services.create_purchase_order_from_rfq(
            db=db,
            user=user,
            rfq_id=8,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "PURCHASE_ORDER_RFQ_INVALID_WINNER"
    )
    assert db.commits == 0
    assert db.rollbacks == 0
