from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import app
import purchase_management.direct_mr_service as direct_service
from purchase_management.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchasePhase,
    PurchasePhaseAllocation,
)
from purchase_management.schemas import (
    PurchaseOrderFromMRCreate,
)


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


def _source(status="approved"):
    return {
        "id": 31,
        "company_id": 3,
        "mr_number": "MR-2026-0031",
        "status": status,
        "needed_by_date": date(
            2026,
            8,
            20,
        ),
        "reason": "Maintenance requirement",
        "notes": None,
        "items": [
            {
                "id": 71,
                "item_id": 101,
                "item_code": "BRG-001",
                "item_name": "Bearing",
                "unit_id": 7,
                "unit_code": "PCS",
                "quantity": Decimal("4"),
                "notes": "Original manufacturer",
            }
        ],
    }


def _payload():
    return {
        "supplier_id": 14,
        "title": None,
        "description": None,
        "expected_delivery_date": None,
        "lines": [
            {
                "requisition_item_id": 71,
                "line_description": None,
                "unit_price": Decimal("12.50"),
                "currency_id": 1,
                "exchange_rate_used": Decimal("1"),
                "notes": None,
            }
        ],
    }


def _patch_dependencies(
    monkeypatch,
    db,
    source=None,
    mark_calls=None,
    prepared_inputs=None,
):
    source = source or _source()
    mark_calls = (
        mark_calls
        if mark_calls is not None
        else []
    )
    prepared_inputs = (
        prepared_inputs
        if prepared_inputs is not None
        else []
    )

    monkeypatch.setattr(
        direct_service,
        "_get_purchase_order_for_mr",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        direct_service,
        "_get_requisition_reference_for_purchase",
        lambda **kwargs: source,
    )
    monkeypatch.setattr(
        direct_service,
        "_resolve_supplier_for_purchase",
        lambda **kwargs: (14, "Vendor A"),
    )
    monkeypatch.setattr(
        direct_service,
        "_get_company_base_currency_reference",
        lambda **kwargs: SimpleNamespace(
            id=1,
            decimal_places=2,
        ),
    )

    def prepare_lines(**kwargs):
        prepared_inputs.append(
            kwargs["lines"]
        )
        source_line = kwargs["lines"][0]

        return [
            {
                "line_number": 1,
                "item_id": source_line["item_id"],
                "ordered_quantity": (
                    source_line[
                        "ordered_quantity"
                    ]
                ),
                "unit_id": source_line["unit_id"],
                "line_description": (
                    source_line[
                        "line_description"
                    ]
                ),
                "unit_price": Decimal("12.50"),
                "currency_id": 1,
                "unit_price_base": Decimal("12.50"),
                "exchange_rate_used": Decimal("1"),
                "notes": source_line["notes"],
            }
        ]

    monkeypatch.setattr(
        direct_service,
        "_prepare_purchase_order_lines",
        prepare_lines,
    )
    monkeypatch.setattr(
        direct_service,
        "_next_reference_number",
        lambda **kwargs: "PO-2026-0031",
    )
    monkeypatch.setattr(
        direct_service,
        "get_po_or_404",
        lambda **kwargs: next(
            item
            for item in db.added
            if isinstance(item, PurchaseOrder)
        ),
    )
    monkeypatch.setattr(
        direct_service,
        "_mark_requisition_ordered_from_purchase_order",
        lambda **kwargs: mark_calls.append(
            {
                **kwargs,
                "commit_count": db.commits,
            }
        ),
    )

    return mark_calls, prepared_inputs


def test_direct_mr_schema_rejects_duplicate_items():
    with pytest.raises(ValidationError):
        PurchaseOrderFromMRCreate(
            supplier_id=14,
            lines=[
                {
                    "requisition_item_id": 71,
                    "unit_price": 10,
                    "currency_id": 1,
                    "exchange_rate_used": 1,
                },
                {
                    "requisition_item_id": 71,
                    "unit_price": 10,
                    "currency_id": 1,
                    "exchange_rate_used": 1,
                },
            ],
        )


def test_direct_mr_schema_rejects_mixed_currency():
    with pytest.raises(ValidationError):
        PurchaseOrderFromMRCreate(
            supplier_id=14,
            lines=[
                {
                    "requisition_item_id": 71,
                    "unit_price": 10,
                    "currency_id": 1,
                    "exchange_rate_used": 1,
                },
                {
                    "requisition_item_id": 72,
                    "unit_price": 10,
                    "currency_id": 2,
                    "exchange_rate_used": 1,
                },
            ],
        )


@pytest.mark.parametrize(
    "duplicated_field",
    [
        {
            "ordered_quantity": Decimal("2"),
        },
        {
            "unit_id": 7,
        },
    ],
)
def test_direct_mr_schema_rejects_mr_owned_facts(
    duplicated_field,
):
    with pytest.raises(ValidationError):
        PurchaseOrderFromMRCreate(
            supplier_id=14,
            lines=[
                {
                    "requisition_item_id": 71,
                    "unit_price": Decimal("10"),
                    "currency_id": 1,
                    "exchange_rate_used": Decimal("1"),
                    **duplicated_field,
                }
            ],
        )


def test_direct_mr_creation_is_atomic(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )
    mark_calls = []
    prepared_inputs = []

    _patch_dependencies(
        monkeypatch,
        db,
        mark_calls=mark_calls,
        prepared_inputs=prepared_inputs,
    )

    result = (
        direct_service
        .create_purchase_order_from_mr(
            db=db,
            user=user,
            requisition_id=31,
            data=_payload(),
        )
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
        if isinstance(
            item,
            PurchasePhaseAllocation,
        )
    )

    assert result is purchase_order
    assert (
        purchase_order
        .source_material_requisition_id
        == 31
    )
    assert purchase_order.rfq_id is None
    assert (
        purchase_order
        .winning_quotation_response_id
        is None
    )

    assert phase.phase_number == 1
    assert (
        phase.expected_delivery_date.date()
        == date(2026, 8, 20)
    )

    assert prepared_inputs[0][0][
        "ordered_quantity"
    ] == Decimal("4")
    assert prepared_inputs[0][0][
        "unit_id"
    ] == 7

    assert line.item_id == 101
    assert line.unit_id == 7
    assert line.ordered_quantity == Decimal("4")
    assert allocation.allocated_quantity == (
        Decimal("4")
    )

    assert len(mark_calls) == 1
    assert mark_calls[0]["commit_count"] == 0
    assert mark_calls[0]["requisition_id"] == 31
    assert db.commits == 1
    assert db.rollbacks == 0


def test_direct_mr_requires_approved_source(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )

    _patch_dependencies(
        monkeypatch,
        db,
        source=_source(status="ordered"),
    )

    with pytest.raises(HTTPException) as exc_info:
        direct_service.create_purchase_order_from_mr(
            db=db,
            user=user,
            requisition_id=31,
            data=_payload(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "PURCHASE_ORDER_MR_NOT_APPROVED"
    )
    assert db.commits == 0


def test_direct_mr_requires_every_source_item(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )
    source = _source()
    source["items"].append(
        {
            "id": 72,
            "item_id": 102,
            "item_code": "SEAL-001",
            "item_name": "Seal",
            "unit_id": 7,
            "unit_code": "PCS",
            "quantity": Decimal("2"),
            "notes": None,
        }
    )

    _patch_dependencies(
        monkeypatch,
        db,
        source=source,
    )

    with pytest.raises(HTTPException) as exc_info:
        direct_service.create_purchase_order_from_mr(
            db=db,
            user=user,
            requisition_id=31,
            data=_payload(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "PURCHASE_ORDER_MR_ITEMS_INCOMPLETE"
    )
    assert db.commits == 0


def test_direct_mr_rejects_unresolved_source_item(
    monkeypatch,
):
    db = FakeSession()
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )
    source = _source()
    source["items"][0]["unit_id"] = None

    _patch_dependencies(
        monkeypatch,
        db,
        source=source,
    )

    with pytest.raises(HTTPException) as exc_info:
        direct_service.create_purchase_order_from_mr(
            db=db,
            user=user,
            requisition_id=31,
            data=_payload(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == (
        "PURCHASE_ORDER_MR_ITEM_INVALID"
    )
    assert db.commits == 0


def test_direct_mr_commit_failure_rolls_back_source_and_po(
    monkeypatch,
):
    db = FakeSession(
        commit_error=RuntimeError(
            "commit failed"
        )
    )
    user = SimpleNamespace(
        id=11,
        company_id=3,
    )
    mark_calls = []

    _patch_dependencies(
        monkeypatch,
        db,
        mark_calls=mark_calls,
    )

    with pytest.raises(
        RuntimeError,
        match="commit failed",
    ):
        direct_service.create_purchase_order_from_mr(
            db=db,
            user=user,
            requisition_id=31,
            data=_payload(),
        )

    assert len(mark_calls) == 1
    assert mark_calls[0]["commit_count"] == 0
    assert db.commits == 1
    assert db.rollbacks == 1


def test_direct_mr_route_is_registered():
    paths = app.openapi()["paths"]

    assert (
        "/purchase/orders/from-mr/{mr_id}"
        in paths
    )
    assert (
        "post"
        in paths[
            "/purchase/orders/from-mr/{mr_id}"
        ]
    )


def test_direct_mr_source_is_unique_per_company():
    constraint_names = {
        constraint.name
        for constraint
        in PurchaseOrder.__table__.constraints
    }

    assert (
        "uq_purchase_orders_company_source_mr"
        in constraint_names
    )
