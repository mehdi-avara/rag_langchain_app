from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from requisition_management.models import MaterialRequisitionStatus
from requisition_management.schemas import MaterialRequisitionItemCreate
from requisition_management.services import (
    _record_status_history,
    get_transition_target,
)


def test_transition_targets_follow_the_mr_workflow():
    assert (
        get_transition_target(
            MaterialRequisitionStatus.DRAFT.value,
            "submit",
        )
        == MaterialRequisitionStatus.SUBMITTED.value
    )
    assert (
        get_transition_target(
            MaterialRequisitionStatus.SUBMITTED.value,
            "start_review",
        )
        == MaterialRequisitionStatus.UNDER_REVIEW.value
    )
    assert (
        get_transition_target(
            MaterialRequisitionStatus.SUBMITTED.value,
            "approve",
        )
        == MaterialRequisitionStatus.APPROVED.value
    )
    assert (
        get_transition_target(
            MaterialRequisitionStatus.UNDER_REVIEW.value,
            "reject",
        )
        == MaterialRequisitionStatus.REJECTED.value
    )


def test_invalid_transition_returns_none():
    assert (
        get_transition_target(
            MaterialRequisitionStatus.APPROVED.value,
            "approve",
        )
        is None
    )
    assert (
        get_transition_target(
            MaterialRequisitionStatus.REJECTED.value,
            "submit",
        )
        is None
    )


def test_estimated_cost_requires_full_currency_pattern():
    with pytest.raises(ValidationError):
        MaterialRequisitionItemCreate(
            item_id=1,
            quantity=Decimal("2"),
            estimated_unit_cost=Decimal("12.5"),
        )


def test_estimated_cost_accepts_complete_currency_pattern():
    item = MaterialRequisitionItemCreate(
        item_id=1,
        quantity=Decimal("2"),
        estimated_unit_cost=Decimal("12.5"),
        currency_id=1,
        estimated_unit_cost_base=Decimal("12.5"),
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
    )

    assert item.estimated_unit_cost == Decimal("12.5")
    assert item.currency_id == 1


class RecordingSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


def test_status_history_is_attached_to_requisition_collection():
    db = RecordingSession()
    requisition = SimpleNamespace(id=15, status_history=[])
    user = SimpleNamespace(id=4)

    _record_status_history(
        db=db,
        requisition=requisition,
        from_status="submitted",
        to_status="approved",
        action="approve",
        current_user=user,
        note="Approved in test",
    )

    assert len(db.added) == 1
    assert len(requisition.status_history) == 1
    assert requisition.status_history[0].from_status == "submitted"
    assert requisition.status_history[0].to_status == "approved"
    assert requisition.status_history[0].changed_by_user_id == 4
