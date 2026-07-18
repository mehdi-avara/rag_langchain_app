from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import purchase_management.services as purchase_services
from purchase_management.models import (
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
    PurchasePhaseStatus,
)
from purchase_management.schemas import PurchaseOrderCreate


class FakeSession:
    def __init__(self, commit_error=None):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self._next_id = 1
        self.commit_error = commit_error

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        return value


def _payload():
    return {
        "title": "Manual bearing order",
        "supplier_id": 14,
        "description": "Required for maintenance",
        "expected_delivery_date": None,
        "lines": [
            {
                "item_id": 101,
                "ordered_quantity": Decimal("2"),
                "unit_id": 7,
                "line_description": "Bearing",
                "unit_price": Decimal("12.50"),
                "currency_id": 1,
                "exchange_rate_used": Decimal("1"),
                "notes": "Original manufacturer",
            }
        ],
    }


def _prepared_lines():
    return [
        {
            "line_number": 1,
            "item_id": 101,
            "ordered_quantity": Decimal("2"),
            "unit_id": 7,
            "line_description": "Bearing",
            "unit_price": Decimal("12.50"),
            "currency_id": 1,
            "unit_price_base": Decimal("12.50"),
            "exchange_rate_used": Decimal("1"),
            "notes": "Original manufacturer",
        }
    ]


def _patch_creation_dependencies(monkeypatch, db):
    monkeypatch.setattr(
        purchase_services,
        "_resolve_supplier_for_purchase",
        lambda **kwargs: (14, "Vendor A"),
    )
    monkeypatch.setattr(
        purchase_services,
        "_get_company_base_currency_reference",
        lambda **kwargs: SimpleNamespace(
            id=1,
            decimal_places=2,
        ),
    )
    monkeypatch.setattr(
        purchase_services,
        "_prepare_purchase_order_lines",
        lambda **kwargs: _prepared_lines(),
    )
    monkeypatch.setattr(
        purchase_services,
        "_next_reference_number",
        lambda **kwargs: "PO-2026-0010",
    )
    monkeypatch.setattr(
        purchase_services,
        "get_po_or_404",
        lambda **kwargs: db.added[0],
    )


def test_purchase_order_schema_requires_lines():
    with pytest.raises(ValidationError):
        PurchaseOrderCreate(
            supplier_id=14,
            lines=[],
        )


def test_purchase_order_schema_rejects_mixed_currency():
    with pytest.raises(ValidationError):
        PurchaseOrderCreate(
            supplier_id=14,
            lines=[
                {
                    "item_id": 1,
                    "ordered_quantity": Decimal("1"),
                    "unit_id": 1,
                    "unit_price": Decimal("10"),
                    "currency_id": 1,
                    "exchange_rate_used": Decimal("1"),
                },
                {
                    "item_id": 2,
                    "ordered_quantity": Decimal("1"),
                    "unit_id": 1,
                    "unit_price": Decimal("10"),
                    "currency_id": 2,
                    "exchange_rate_used": Decimal("1"),
                },
            ],
        )


def test_manual_creation_builds_atomic_normalized_graph(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(id=11, company_id=3)

    _patch_creation_dependencies(monkeypatch, db)

    result = purchase_services.create_purchase_order(
        db=db,
        user=user,
        data=_payload(),
    )

    purchase_order = next(
        item
        for item in db.added
        if isinstance(item, PurchaseOrder)
    )
    phase = next(
        item
        for item in db.added
        if isinstance(item, PurchasePhase)
    )
    line = next(
        item
        for item in db.added
        if isinstance(item, PurchaseOrderLine)
    )
    allocation = next(
        item
        for item in db.added
        if isinstance(item, PurchasePhaseAllocation)
    )

    assert result is purchase_order
    assert purchase_order.reference_number == "PO-2026-0010"
    assert purchase_order.supplier_id == 14
    assert purchase_order.supplier_name == "Vendor A"
    assert purchase_order.currency_id == 1
    assert purchase_order.base_currency_id == 1
    assert purchase_order.status == PurchaseOrderStatus.DRAFT.value
    assert purchase_order.approval_status == (
        PurchaseApprovalStatus.DRAFT.value
    )

    assert phase.purchase_order_id == purchase_order.id
    assert phase.phase_number == 1
    assert phase.status == PurchasePhaseStatus.DRAFT.value

    assert line.purchase_order_id == purchase_order.id
    assert line.line_number == 1
    assert line.item_id == 101
    assert line.ordered_quantity == Decimal("2")
    assert line.unit_price_base == Decimal("12.50")

    assert allocation.phase_id == phase.id
    assert allocation.purchase_order_line_id == line.id
    assert allocation.allocated_quantity == Decimal("2")

    assert db.commits == 1
    assert db.rollbacks == 0


def test_manual_creation_rolls_back_as_one_transaction(
    monkeypatch,
):
    db = FakeSession(
        commit_error=RuntimeError("commit failed")
    )
    user = SimpleNamespace(id=11, company_id=3)

    _patch_creation_dependencies(monkeypatch, db)

    with pytest.raises(
        RuntimeError,
        match="commit failed",
    ):
        purchase_services.create_purchase_order(
            db=db,
            user=user,
            data=_payload(),
        )

    assert db.commits == 1
    assert db.rollbacks == 1
