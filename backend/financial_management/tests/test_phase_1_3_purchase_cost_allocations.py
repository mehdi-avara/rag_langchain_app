from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import financial_management.purchase_cost_allocation_service as service
from financial_management.models import (
    PurchaseCostPaymentAllocation,
)


BACKEND_ROOT = Path(__file__).parents[2]


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshes = 0
        self.flushes = 0

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshes += 1

    def flush(self):
        self.flushes += 1


def current_user():
    return SimpleNamespace(
        id=31,
        company_id=7,
    )


def receipt(
    *,
    direction="output",
    amount_base="20",
):
    return SimpleNamespace(
        id=51,
        company_id=7,
        direction=direction,
        currency_id=1,
        base_currency_id=1,
        amount_base=Decimal(
            amount_base
        ),
        exchange_rate_used=Decimal("1"),
    )


def payload(
    *,
    cost_id=41,
    amount="4",
):
    return {
        "purchase_order_cost_id": cost_id,
        "allocated_amount": Decimal(
            amount
        ),
        "currency_id": 1,
        "exchange_rate_used": (
            Decimal("1")
        ),
    }


def prepared(
    *,
    cost_id=41,
    amount="4",
    supplier_id=9,
    target_base="10",
):
    value = Decimal(amount)

    return (
        {
            "purchase_order_cost_id": (
                cost_id
            ),
            "allocated_amount": value,
            "currency_id": 1,
            "allocated_amount_base": value,
            "exchange_rate_used": (
                Decimal("1")
            ),
        },
        {
            "cost_id": cost_id,
            "company_id": 7,
            "supplier_id": supplier_id,
            "target_amount_base": Decimal(
                target_base
            ),
        },
    )


def test_input_receipt_is_rejected():
    with pytest.raises(
        HTTPException
    ) as error:
        service._validate_receipt_context(
            receipt(direction="input")
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_"
        "DIRECTION_INVALID_FOR_PURCHASE"
    )


def test_incomplete_canonical_receipt_is_rejected():
    current = receipt()
    current.currency_id = None

    with pytest.raises(
        HTTPException
    ) as error:
        service._validate_receipt_context(
            current
        )

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_"
        "ALLOCATION_CURRENCY_MISMATCH"
    )


def test_nonfinancial_receipt_edit_is_allowed(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "receipt_has_purchase_cost_allocations",
        lambda **kwargs: True,
    )

    service.assert_receipt_financial_edit_allowed(
        db=FakeSession(),
        receipt=receipt(),
        changed_fields={
            "description",
            "tracking_number",
        },
    )


def test_allocated_receipt_financial_edit_blocked(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "receipt_has_purchase_cost_allocations",
        lambda **kwargs: True,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.assert_receipt_financial_edit_allowed(
            db=FakeSession(),
            receipt=receipt(),
            changed_fields={
                "amount",
            },
        )

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_HAS_ALLOCATIONS"
    )


def test_allocated_receipt_delete_blocked(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "receipt_has_purchase_cost_allocations",
        lambda **kwargs: True,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.assert_receipt_delete_allowed(
            db=FakeSession(),
            receipt=receipt(),
        )

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_HAS_ALLOCATIONS"
    )


def test_supplier_mismatch_is_blocked(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt()

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: {9},
    )
    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        lambda **kwargs: prepared(
            supplier_id=10,
        ),
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(),
            ],
        )

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_"
        "ALLOCATION_SUPPLIER_MISMATCH"
    )
    assert db.commits == 0


def test_receipt_overallocation_is_blocked(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt(
        amount_base="5"
    )

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: set(),
    )
    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        lambda **kwargs: prepared(
            amount="6",
            target_base="10",
        ),
    )
    monkeypatch.setattr(
        service,
        "_receipt_allocated_base",
        lambda **kwargs: Decimal("0"),
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(amount="6"),
            ],
        )

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_"
        "ALLOCATION_EXCEEDS_RECEIPT"
    )
    assert db.commits == 0


def test_cost_overallocation_is_blocked(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt(
        amount_base="100"
    )

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: set(),
    )
    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        lambda **kwargs: prepared(
            amount="6",
            target_base="5",
        ),
    )
    monkeypatch.setattr(
        service,
        "_receipt_allocated_base",
        lambda **kwargs: Decimal("0"),
    )
    monkeypatch.setattr(
        service,
        "_cost_allocated_base",
        lambda **kwargs: Decimal("0"),
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(amount="6"),
            ],
        )

    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_"
        "ALLOCATION_EXCEEDS_COST"
    )
    assert db.commits == 0


def test_batch_cost_total_is_validated(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt(
        amount_base="100"
    )

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: set(),
    )

    def prepare(**kwargs):
        return prepared(
            cost_id=41,
            amount=str(
                kwargs["allocated_amount"]
            ),
            target_base="7",
        )

    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        prepare,
    )
    monkeypatch.setattr(
        service,
        "_receipt_allocated_base",
        lambda **kwargs: Decimal("0"),
    )
    monkeypatch.setattr(
        service,
        "_cost_allocated_base",
        lambda **kwargs: Decimal("0"),
    )

    with pytest.raises(
        HTTPException
    ) as error:
        service.create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(amount="4"),
                payload(amount="4"),
            ],
        )

    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_"
        "ALLOCATION_EXCEEDS_COST"
    )


def test_successful_allocation_creation(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt(
        amount_base="20"
    )

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: set(),
    )

    def prepare(**kwargs):
        return prepared(
            cost_id=int(
                kwargs[
                    "purchase_order_cost_id"
                ]
            ),
            amount=str(
                kwargs["allocated_amount"]
            ),
            supplier_id=9,
            target_base="10",
        )

    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        prepare,
    )
    monkeypatch.setattr(
        service,
        "_receipt_allocated_base",
        lambda **kwargs: Decimal("0"),
    )
    monkeypatch.setattr(
        service,
        "_cost_allocated_base",
        lambda **kwargs: Decimal("0"),
    )

    result = (
        service
        .create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(
                    cost_id=41,
                    amount="4",
                ),
                payload(
                    cost_id=42,
                    amount="5",
                ),
            ],
        )
    )

    assert len(result) == 2

    assert all(
        isinstance(
            item,
            PurchaseCostPaymentAllocation,
        )
        for item in result
    )

    assert [
        item.purchase_order_cost_id
        for item in result
    ] == [
        41,
        42,
    ]

    assert [
        item.allocated_amount_base
        for item in result
    ] == [
        Decimal("4"),
        Decimal("5"),
    ]

    assert all(
        item.company_id == 7
        for item in result
    )

    assert all(
        item.financial_receipt_id == 51
        for item in result
    )

    assert all(
        item.created_by_user_id == 31
        for item in result
    )

    assert db.commits == 1
    assert db.refreshes == 2


def test_commit_false_flushes_without_commit(
    monkeypatch,
):
    db = FakeSession()
    current_receipt = receipt()

    monkeypatch.setattr(
        service,
        "get_receipt_for_allocation",
        lambda **kwargs: current_receipt,
    )
    monkeypatch.setattr(
        service,
        "_validate_receipt_context",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "_existing_receipt_supplier_ids",
        lambda **kwargs: set(),
    )
    monkeypatch.setattr(
        service,
        "_prepare_allocation",
        lambda **kwargs: prepared(),
    )
    monkeypatch.setattr(
        service,
        "_receipt_allocated_base",
        lambda **kwargs: Decimal("0"),
    )
    monkeypatch.setattr(
        service,
        "_cost_allocated_base",
        lambda **kwargs: Decimal("0"),
    )

    result = (
        service
        .create_purchase_cost_allocations(
            db=db,
            current_user=current_user(),
            receipt_id=current_receipt.id,
            allocations=[
                payload(),
            ],
            commit=False,
        )
    )

    assert len(result) == 1
    assert db.commits == 0
    assert db.flushes == 1
    assert db.refreshes == 0


def test_allocation_delete_commits(
    monkeypatch,
):
    db = FakeSession()

    allocation = SimpleNamespace(
        id=71,
        company_id=7,
        financial_receipt_id=51,
        purchase_order_cost_id=41,
        allocated_amount=Decimal("4"),
        allocated_amount_base=(
            Decimal("4")
        ),
    )

    monkeypatch.setattr(
        service,
        "get_purchase_cost_allocation",
        lambda **kwargs: allocation,
    )

    service.delete_purchase_cost_allocation(
        db=db,
        current_user=current_user(),
        receipt_id=51,
        allocation_id=71,
    )

    assert db.deleted == [
        allocation,
    ]
    assert db.commits == 1


def test_finance_does_not_import_purchase_models():
    source = (
        BACKEND_ROOT
        / "financial_management"
        / "purchase_cost_allocation_service.py"
    ).read_text(encoding="utf-8")

    assert (
        "from purchase_management.models"
        not in source
    )

    assert (
        "from purchase_management.services import"
        in source
    )


def test_allocation_openapi_contract():
    from api import app

    openapi = app.openapi()

    expected = {
        (
            "GET",
            (
                "/financial_management/"
                "receipts/{receipt_id}/"
                "purchase-cost-allocations"
            ),
        ),
        (
            "POST",
            (
                "/financial_management/"
                "receipts/{receipt_id}/"
                "purchase-cost-allocations"
            ),
        ),
        (
            "DELETE",
            (
                "/financial_management/"
                "receipts/{receipt_id}/"
                "purchase-cost-allocations/"
                "{allocation_id}"
            ),
        ),
    }

    actual = {
        (
            method.upper(),
            path,
        )
        for path, definition
        in openapi["paths"].items()
        for method in definition
        if (
            method.lower()
            in {
                "get",
                "post",
                "delete",
            }
            and "purchase-cost-allocations"
            in path
        )
    }

    assert actual == expected
