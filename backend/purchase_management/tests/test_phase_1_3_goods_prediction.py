from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


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

sys.path.insert(
    0,
    str(
        Path(__file__)
        .resolve()
        .parents[2]
    ),
)


from financial_management import services as finance_services  # noqa: E402
from purchase_management import amendment_service  # noqa: E402
from purchase_management import services  # noqa: E402
from purchase_management.models import (  # noqa: E402
    PurchaseApprovalStatus,
    PurchaseAmendmentStatus,
    PurchaseOrderCost,
    PurchaseOrderStatus,
    PurchasePhaseStatus,
)


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.refreshes = 0

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshes += 1


def user():
    return SimpleNamespace(
        id=31,
        company_id=7,
    )


def line(
    *,
    quantity="2",
    unit_price="10",
    unit_price_base="15",
    currency_id=2,
    exchange_rate="1.5",
):
    return SimpleNamespace(
        ordered_quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        unit_price_base=Decimal(
            unit_price_base
        ),
        currency_id=currency_id,
        exchange_rate_used=Decimal(
            exchange_rate
        ),
    )


def phase():
    return SimpleNamespace(
        status=PurchasePhaseStatus.DRAFT.value
    )


def po(
    *,
    lines=None,
    costs=None,
    approval_status=None,
):
    return SimpleNamespace(
        id=15,
        company_id=7,
        status=PurchaseOrderStatus.DRAFT.value,
        approval_status=(
            approval_status
            or PurchaseApprovalStatus
            .PENDING
            .value
        ),
        approved_by_user_id=None,
        lines=list(
            lines
            if lines is not None
            else [line()]
        ),
        costs=list(costs or []),
        phases=[phase()],
        active_amendment=None,
    )


def bundle(
    *,
    amount="20",
    amount_base="30",
):
    return {
        "amount": Decimal(amount),
        "currency_id": 2,
        "amount_base": Decimal(
            amount_base
        ),
        "base_currency_id": 1,
        "exchange_rate_used": Decimal(
            "1.5"
        ),
    }


def goods_cost(
    *,
    predicted="20",
    predicted_base="30",
    actual=None,
):
    return SimpleNamespace(
        id=41,
        purchase_order_id=15,
        cost_type="goods",
        description="Goods",
        amount=Decimal(predicted),
        currency_id=2,
        amount_base=Decimal(
            predicted_base
        ),
        base_currency_id=1,
        exchange_rate_used=Decimal(
            "1.5"
        ),
        allocation_method="per_value",
        predicted_amount=Decimal(
            predicted
        ),
        predicted_currency_id=2,
        predicted_amount_base=Decimal(
            predicted_base
        ),
        predicted_exchange_rate_used=(
            Decimal("1.5")
        ),
        actual_amount=(
            Decimal(str(actual))
            if actual is not None
            else None
        ),
        actual_currency_id=(
            2
            if actual is not None
            else None
        ),
        actual_amount_base=(
            Decimal(str(actual))
            if actual is not None
            else None
        ),
        actual_exchange_rate_used=(
            Decimal("1.5")
            if actual is not None
            else None
        ),
    )


def test_initial_approval_creates_goods_prediction(
    monkeypatch,
):
    db = FakeSession()
    purchase_order = po()

    monkeypatch.setattr(
        services,
        "get_po_or_404",
        lambda **_kwargs: purchase_order,
    )

    monkeypatch.setattr(
        services,
        (
            "_build_purchase_order_goods_"
            "prediction_bundle"
        ),
        lambda **_kwargs: bundle(),
    )

    result = services.process_approval(
        db=db,
        user=user(),
        po_id=15,
        action="approve",
        note=None,
    )

    assert result is purchase_order
    assert purchase_order.status == "ordered"
    assert (
        purchase_order.approval_status
        == "approved"
    )
    assert db.commits == 1
    assert len(db.added) == 1

    created = db.added[0]

    assert isinstance(
        created,
        PurchaseOrderCost,
    )
    assert created.cost_type == "goods"
    assert created.predicted_amount == (
        Decimal("20")
    )
    assert (
        created.predicted_amount_base
        == Decimal("30")
    )
    assert created.created_by_user_id == 31


def test_existing_unprotected_goods_is_updated(
    monkeypatch,
):
    db = FakeSession()
    existing = goods_cost(
        predicted="10",
        predicted_base="15",
    )
    purchase_order = po(
        costs=[existing]
    )

    monkeypatch.setattr(
        services,
        (
            "_build_purchase_order_goods_"
            "prediction_bundle"
        ),
        lambda **_kwargs: bundle(),
    )

    monkeypatch.setattr(
        services,
        "_get_purchase_order_cost_paid_base",
        lambda **_kwargs: Decimal("0"),
    )

    status_value = (
        services
        ._synchronize_purchase_order_goods_prediction(
            db=db,
            user=user(),
            purchase_order=purchase_order,
        )
    )

    assert status_value == "synced"
    assert existing.predicted_amount == (
        Decimal("20")
    )
    assert (
        existing.predicted_amount_base
        == Decimal("30")
    )
    assert existing.amount == Decimal("20")
    assert existing.amount_base == Decimal("30")
    assert db.added == []


@pytest.mark.parametrize(
    ("actual", "paid"),
    [
        ("18", "0"),
        (None, "5"),
    ],
)
def test_protected_goods_prediction_is_preserved(
    monkeypatch,
    actual,
    paid,
):
    db = FakeSession()
    existing = goods_cost(
        predicted="10",
        predicted_base="15",
        actual=actual,
    )
    purchase_order = po(
        costs=[existing]
    )

    monkeypatch.setattr(
        services,
        (
            "_build_purchase_order_goods_"
            "prediction_bundle"
        ),
        lambda **_kwargs: bundle(),
    )

    monkeypatch.setattr(
        services,
        "_get_purchase_order_cost_paid_base",
        lambda **_kwargs: Decimal(paid),
    )

    status_value = (
        services
        ._synchronize_purchase_order_goods_prediction(
            db=db,
            user=user(),
            purchase_order=purchase_order,
        )
    )

    assert (
        status_value
        == "payment_review_required"
    )
    assert existing.predicted_amount == (
        Decimal("10")
    )
    assert (
        existing.predicted_amount_base
        == Decimal("15")
    )


def test_amendment_approval_synchronizes_goods(
    monkeypatch,
):
    db = FakeSession()
    purchase_order = po(
        approval_status=(
            PurchaseApprovalStatus
            .PENDING
            .value
        )
    )
    amendment = SimpleNamespace(
        status=PurchaseAmendmentStatus.PENDING.value,
        before_snapshot={},
        decision_note=None,
        decided_by_user_id=None,
        decided_at=None,
        updated_at=None,
    )
    calls = []

    monkeypatch.setattr(
        amendment_service,
        "_get_amendment_or_404",
        lambda **_kwargs: amendment,
    )

    monkeypatch.setattr(
        amendment_service,
        "get_po_or_404",
        lambda **_kwargs: purchase_order,
    )

    monkeypatch.setattr(
        amendment_service,
        (
            "_synchronize_purchase_order_"
            "goods_prediction"
        ),
        lambda **kwargs: (
            calls.append(kwargs)
            or "synced"
        ),
    )

    amendment_service.decide_purchase_order_amendment(
        db=db,
        user=user(),
        purchase_order_id=15,
        amendment_id=3,
        action="approve",
        note="Approved",
    )

    assert len(calls) == 1
    assert (
        calls[0]["purchase_order"]
        is purchase_order
    )
    assert amendment.status == "approved"
    assert (
        purchase_order.approval_status
        == "approved"
    )
    assert db.commits == 1


def test_stale_protected_goods_returns_review_state(
    monkeypatch,
):
    purchase_order = po(
        lines=[
            line(
                quantity="4",
                unit_price_base="15",
            )
        ],
        costs=[
            goods_cost(
                predicted="20",
                predicted_base="30",
            )
        ],
    )

    monkeypatch.setattr(
        services,
        "get_po_or_404",
        lambda **_kwargs: purchase_order,
    )

    monkeypatch.setattr(
        services,
        (
            "_get_company_base_currency_"
            "reference"
        ),
        lambda **_kwargs: SimpleNamespace(
            id=1,
            decimal_places=0,
        ),
    )

    monkeypatch.setattr(
        services,
        (
            "_purchase_order_has_untracked_"
            "legacy_payments"
        ),
        lambda **_kwargs: False,
    )

    monkeypatch.setattr(
        finance_services,
        "get_purchase_cost_payment_summaries",
        lambda **_kwargs: {
            41: {
                "cost_id": 41,
                "paid_base": Decimal("5"),
            }
        },
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    row = result["costs"][0]

    assert (
        row["payment_state"]
        == "payment_review_required"
    )
    assert (
        row["settlement_target_base"]
        == Decimal("30")
    )
    assert (
        row["outstanding_base"]
        == Decimal("25")
    )


def test_goods_is_not_commercially_double_counted(
    monkeypatch,
):
    purchase_order = SimpleNamespace(
        id=15,
        company_id=7,
        reference_number="PO-TEST",
        lines=[
            line(
                quantity="2",
                unit_price="50",
                unit_price_base="50",
                currency_id=1,
                exchange_rate="1",
            )
        ],
        costs=[
            goods_cost(
                predicted="100",
                predicted_base="100",
            ),
            SimpleNamespace(
                cost_type="freight",
                amount_base=Decimal("20"),
            ),
        ],
        phases=[],
    )

    monkeypatch.setattr(
        services,
        "get_po_or_404",
        lambda *_args, **_kwargs: (
            purchase_order
        ),
    )

    monkeypatch.setattr(
        services,
        (
            "_get_company_base_currency_"
            "reference"
        ),
        lambda **_kwargs: SimpleNamespace(
            id=1,
        ),
    )

    result = services.get_summary(
        db=object(),
        user=user(),
        po_id=15,
    )

    assert result["total_in_base"] == (
        Decimal("100")
    )
    assert (
        result["additional_costs_base"]
        == Decimal("20")
    )
    assert (
        result["grand_total_base"]
        == Decimal("120")
    )


def test_duplicate_manual_goods_cost_is_blocked(
    monkeypatch,
):
    db = FakeSession()
    purchase_order = po(
        costs=[goods_cost()]
    )

    monkeypatch.setattr(
        services,
        "get_po_or_404",
        lambda **_kwargs: purchase_order,
    )

    with pytest.raises(HTTPException) as error:
        services.add_cost(
            db=db,
            user=user(),
            po_id=15,
            cost_type="goods",
            description=None,
            predicted_amount=Decimal("20"),
            predicted_currency_id=2,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_"
        "NOT_FINANCIALLY_EDITABLE"
    )
    assert db.commits == 0
