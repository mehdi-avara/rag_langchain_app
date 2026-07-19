from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import purchase_management.amendment_service as service
from purchase_management.models import (
    PurchaseAmendmentStatus,
    PurchaseApprovalStatus,
    PurchaseOrderAmendment,
    PurchaseOrderStatus,
)


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        return value


def purchase_order(
    approval_status=(
        PurchaseApprovalStatus.APPROVED.value
    ),
    status=PurchaseOrderStatus.ORDERED.value,
):
    line = SimpleNamespace(
        id=4,
        line_number=1,
        item_id=8,
        ordered_quantity=Decimal("2"),
        unit_id=3,
        line_description="Line",
        unit_price=Decimal("10"),
        currency_id=2,
        unit_price_base=Decimal("10"),
        exchange_rate_used=Decimal("1"),
        notes=None,
        allocations=[
            SimpleNamespace(
                id=9,
                phase_id=5,
                allocated_quantity=Decimal("2"),
            )
        ],
    )
    cost = SimpleNamespace(
        id=6,
        cost_type="freight",
        description="Freight",
        amount=Decimal("5"),
        currency_id=2,
        amount_base=Decimal("5"),
        base_currency_id=2,
        exchange_rate_used=Decimal("1"),
        allocation_method="per_value",
    )

    return SimpleNamespace(
        id=10,
        company_id=2,
        supplier_id=7,
        title="Original",
        description="Original description",
        approval_status=approval_status,
        approved_by_user_id=11,
        status=status,
        lines=[line],
        costs=[cost],
        phases=[],
    )


def test_snapshot_contains_commercial_state():
    po = purchase_order()

    snapshot = (
        service
        .build_purchase_order_commercial_snapshot(
            po
        )
    )

    assert snapshot["header"] == {
        "supplier_id": 7,
        "title": "Original",
        "description": "Original description",
    }
    assert snapshot["lines"][0][
        "ordered_quantity"
    ] == "2"
    assert snapshot["costs"][0][
        "amount"
    ] == "5"
    assert snapshot["lines"][0][
        "allocations"
    ] == [
        {
            "id": 9,
            "phase_id": 5,
            "allocated_quantity": "2",
        }
    ]
    assert snapshot["approval"][
        "approval_status"
    ] == "approved"


def test_draft_order_is_commercially_editable(
    monkeypatch,
):
    po = purchase_order(
        approval_status="draft",
        status="draft",
    )

    monkeypatch.setattr(
        service,
        "get_active_purchase_order_amendment",
        lambda **kwargs: None,
    )

    assert (
        service
        .assert_purchase_order_commercially_editable(
            db=FakeSession(),
            purchase_order=po,
        )
        is None
    )


def test_approved_order_requires_amendment(
    monkeypatch,
):
    po = purchase_order()

    monkeypatch.setattr(
        service,
        "get_active_purchase_order_amendment",
        lambda **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.assert_purchase_order_commercially_editable(
            db=FakeSession(),
            purchase_order=po,
        )

    assert exc.value.detail["code"] == (
        "PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE"
    )


def test_draft_amendment_unlocks_commercial_edits(
    monkeypatch,
):
    po = purchase_order(
        approval_status="draft",
    )
    amendment = SimpleNamespace(
        status=PurchaseAmendmentStatus.DRAFT.value
    )

    monkeypatch.setattr(
        service,
        "get_active_purchase_order_amendment",
        lambda **kwargs: amendment,
    )

    assert (
        service
        .assert_purchase_order_commercially_editable(
            db=FakeSession(),
            purchase_order=po,
        )
        is amendment
    )


def test_pending_amendment_blocks_commercial_edits(
    monkeypatch,
):
    po = purchase_order(
        approval_status="pending",
    )
    amendment = SimpleNamespace(
        status=(
            PurchaseAmendmentStatus.PENDING.value
        )
    )

    monkeypatch.setattr(
        service,
        "get_active_purchase_order_amendment",
        lambda **kwargs: amendment,
    )

    with pytest.raises(HTTPException) as exc:
        service.assert_purchase_order_commercially_editable(
            db=FakeSession(),
            purchase_order=po,
        )

    assert exc.value.detail["code"] == (
        "PURCHASE_ORDER_AMENDMENT_NOT_EDITABLE"
    )


def test_submit_amendment_captures_proposed_snapshot(
    monkeypatch,
):
    po = purchase_order(
        approval_status="draft",
    )
    before = (
        service
        .build_purchase_order_commercial_snapshot(
            po
        )
    )
    before["header"]["title"] = "Before"

    amendment = SimpleNamespace(
        status=PurchaseAmendmentStatus.DRAFT.value,
        before_snapshot=before,
        proposed_snapshot=None,
        submission_note=None,
        submitted_by_user_id=None,
        submitted_at=None,
        updated_at=None,
    )
    db = FakeSession()
    user = SimpleNamespace(id=30)

    monkeypatch.setattr(
        service,
        "_get_amendment_or_404",
        lambda **kwargs: amendment,
    )
    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "_assert_purchase_order_ready_for_submission",
        lambda value: None,
    )

    result = (
        service
        .submit_purchase_order_amendment(
            db=db,
            user=user,
            purchase_order_id=10,
            amendment_id=3,
            note="  Submit note  ",
        )
    )

    assert result is amendment
    assert amendment.status == "pending"
    assert amendment.submission_note == (
        "Submit note"
    )
    assert amendment.proposed_snapshot[
        "header"
    ]["title"] == "Original"
    assert po.approval_status == "pending"
    assert db.commits == 1


def test_approve_amendment_reapproves_order(
    monkeypatch,
):
    po = purchase_order(
        approval_status="pending",
    )
    amendment = SimpleNamespace(
        status=PurchaseAmendmentStatus.PENDING.value,
        before_snapshot={},
        decision_note=None,
        decided_by_user_id=None,
        decided_at=None,
        updated_at=None,
    )
    db = FakeSession()
    user = SimpleNamespace(id=44)

    monkeypatch.setattr(
        service,
        "_get_amendment_or_404",
        lambda **kwargs: amendment,
    )
    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )

    service.decide_purchase_order_amendment(
        db=db,
        user=user,
        purchase_order_id=10,
        amendment_id=5,
        action="approve",
        note="Approved",
    )

    assert amendment.status == "approved"
    assert amendment.decision_note == "Approved"
    assert po.approval_status == "approved"
    assert po.approved_by_user_id == 44
    assert db.commits == 1


def test_reject_amendment_restores_snapshot(
    monkeypatch,
):
    po = purchase_order(
        approval_status="pending",
    )
    before = (
        service
        .build_purchase_order_commercial_snapshot(
            po
        )
    )
    before["header"]["title"] = "Restored"
    before["approval"][
        "approval_status"
    ] = PurchaseApprovalStatus.APPROVED.value
    before["approval"][
        "approved_by_user_id"
    ] = 19

    amendment = SimpleNamespace(
        status=PurchaseAmendmentStatus.PENDING.value,
        before_snapshot=before,
        decision_note=None,
        decided_by_user_id=None,
        decided_at=None,
        updated_at=None,
    )
    db = FakeSession()
    user = SimpleNamespace(id=55)

    monkeypatch.setattr(
        service,
        "_get_amendment_or_404",
        lambda **kwargs: amendment,
    )
    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "restore_purchase_order_commercial_snapshot",
        lambda db, purchase_order, snapshot: (
            setattr(
                purchase_order,
                "title",
                snapshot["header"]["title"],
            ),
            setattr(
                purchase_order,
                "approval_status",
                snapshot["approval"][
                    "approval_status"
                ],
            ),
            setattr(
                purchase_order,
                "approved_by_user_id",
                snapshot["approval"][
                    "approved_by_user_id"
                ],
            ),
        ),
    )

    service.decide_purchase_order_amendment(
        db=db,
        user=user,
        purchase_order_id=10,
        amendment_id=5,
        action="reject",
        note="Rejected",
    )

    assert amendment.status == "rejected"
    assert po.title == "Restored"
    assert po.approval_status == "approved"
    assert po.approved_by_user_id == 19
    assert db.commits == 1



def test_open_amendment_rejects_blank_reason():
    with pytest.raises(HTTPException) as exc:
        service.open_purchase_order_amendment(
            db=None,
            user=None,
            purchase_order_id=1,
            reason=" ",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": (
            "PURCHASE_ORDER_AMENDMENT_"
            "REASON_REQUIRED"
        ),
        "message": (
            "Amendment reason is required"
        ),
    }
