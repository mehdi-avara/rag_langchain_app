from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

import purchase_management.services as service
from purchase_management.models import (
    PurchaseOrderCost,
)
from purchase_management.routes.costs import (
    router as cost_router,
)
from purchase_management.schemas import (
    PurchaseOrderCostCreate,
    PurchaseOrderCostUpdate,
)


BACKEND_ROOT = Path(__file__).parents[2]


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshes = 0

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshes += 1


def user():
    return SimpleNamespace(
        id=31,
        company_id=7,
    )


def purchase_order():
    return SimpleNamespace(
        id=15,
        company_id=7,
        supplier_id=9,
        status="closed",
        approval_status="approved",
    )


def cost():
    return SimpleNamespace(
        id=41,
        purchase_order_id=15,
        cost_type="freight",
        description="Freight",
        amount=Decimal("10"),
        currency_id=1,
        amount_base=Decimal("10"),
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
        allocation_method="per_value",
        predicted_amount=Decimal("10"),
        predicted_currency_id=1,
        predicted_amount_base=Decimal("10"),
        predicted_exchange_rate_used=(
            Decimal("1")
        ),
        actual_amount=None,
        actual_currency_id=None,
        actual_amount_base=None,
        actual_exchange_rate_used=None,
        actual_confirmed_at=None,
        actual_confirmed_by_user_id=None,
    )


def money(
    amount: str,
    currency_id: int = 1,
):
    value = Decimal(amount)

    return {
        "amount": value,
        "currency_id": currency_id,
        "amount_base": value,
        "base_currency_id": 1,
        "exchange_rate_used": Decimal("1"),
    }


def test_create_schema_accepts_legacy_aliases():
    payload = PurchaseOrderCostCreate(
        cost_type="freight",
        amount=Decimal("12.50"),
        currency_id=3,
    )

    assert payload.predicted_amount == (
        Decimal("12.50")
    )
    assert (
        payload.predicted_currency_id
        == 3
    )


def test_create_schema_requires_predicted_money():
    with pytest.raises(ValidationError):
        PurchaseOrderCostCreate(
            cost_type="freight",
        )


def test_create_schema_rejects_base_amount():
    with pytest.raises(ValidationError):
        PurchaseOrderCostCreate.model_validate(
            {
                "cost_type": "freight",
                "predicted_amount": "10",
                "predicted_currency_id": 1,
                "amount_base": "10",
            }
        )


def test_update_schema_maps_legacy_aliases():
    payload = PurchaseOrderCostUpdate(
        amount=Decimal("8"),
        currency_id=2,
    )

    assert payload.predicted_amount == (
        Decimal("8")
    )
    assert (
        payload.predicted_currency_id
        == 2
    )


def test_money_bundle_uses_server_rate(
    monkeypatch,
):
    po = purchase_order()

    monkeypatch.setattr(
        service,
        "_get_company_base_currency_reference",
        lambda **kwargs: SimpleNamespace(
            id=1,
            code="IRT",
            decimal_places=2,
            is_active=True,
        ),
    )

    monkeypatch.setattr(
        service,
        "get_currency_or_404",
        lambda **kwargs: SimpleNamespace(
            id=2,
            code="USD",
            decimal_places=2,
            is_active=True,
        ),
    )

    monkeypatch.setattr(
        service,
        "get_rate",
        lambda **kwargs: Decimal("50000"),
    )

    result = (
        service
        ._prepare_purchase_order_cost_money_bundle(
            db=FakeSession(),
            purchase_order=po,
            amount=Decimal("2.50"),
            currency_id=2,
        )
    )

    assert result["amount"] == (
        Decimal("2.50")
    )
    assert result["exchange_rate_used"] == (
        Decimal("50000.0000000000")
    )
    assert result["amount_base"] == (
        Decimal("125000.00")
    )


def test_cost_creation_ignores_po_lifecycle(
    monkeypatch,
):
    db = FakeSession()
    po = purchase_order()

    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        (
            "_prepare_purchase_order_"
            "cost_money_bundle"
        ),
        lambda **kwargs: money("14"),
    )
    monkeypatch.setattr(
        service,
        (
            "_assert_purchase_order_"
            "commercial_mutation_allowed"
        ),
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "Commercial guard must not run"
            )
        ),
    )

    result = service.add_cost(
        db=db,
        user=user(),
        po_id=15,
        cost_type="freight",
        description="  Transport  ",
        predicted_amount=Decimal("14"),
        predicted_currency_id=1,
    )

    assert isinstance(
        result,
        PurchaseOrderCost,
    )
    assert result.cost_type == "freight"
    assert result.description == "Transport"
    assert result.predicted_amount == (
        Decimal("14")
    )
    assert result.amount == Decimal("14")
    assert result.created_by_user_id == 31
    assert db.commits == 1


def test_paid_cost_currency_change_blocked(
    monkeypatch,
):
    db = FakeSession()
    po = purchase_order()
    current_cost = cost()

    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_or_404",
        lambda **kwargs: current_cost,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_paid_base",
        lambda **kwargs: Decimal("3"),
    )

    with pytest.raises(HTTPException) as error:
        service.update_cost(
            db=db,
            user=user(),
            po_id=15,
            cost_id=41,
            data={
                "predicted_currency_id": 2,
            },
        )

    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_HAS_PAYMENTS"
    )
    assert db.commits == 0


def test_paid_cost_cannot_be_deleted(
    monkeypatch,
):
    db = FakeSession()
    po = purchase_order()
    current_cost = cost()

    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_or_404",
        lambda **kwargs: current_cost,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_paid_base",
        lambda **kwargs: Decimal("1"),
    )

    with pytest.raises(HTTPException) as error:
        service.delete_cost(
            db=db,
            user=user(),
            po_id=15,
            cost_id=41,
        )

    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_HAS_PAYMENTS"
    )
    assert db.deleted == []


def test_actual_below_paid_is_blocked(
    monkeypatch,
):
    db = FakeSession()
    po = purchase_order()
    current_cost = cost()

    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_or_404",
        lambda **kwargs: current_cost,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_paid_base",
        lambda **kwargs: Decimal("8"),
    )
    monkeypatch.setattr(
        service,
        (
            "_prepare_purchase_order_"
            "cost_money_bundle"
        ),
        lambda **kwargs: money("7"),
    )

    with pytest.raises(HTTPException) as error:
        service.confirm_purchase_order_cost_actual(
            db=db,
            user=user(),
            po_id=15,
            cost_id=41,
            amount=Decimal("7"),
            currency_id=1,
        )

    assert error.value.detail["code"] == (
        "PURCHASE_ORDER_COST_ACTUAL_BELOW_PAID"
    )


def test_actual_confirmation_sets_audit(
    monkeypatch,
):
    db = FakeSession()
    po = purchase_order()
    current_cost = cost()

    monkeypatch.setattr(
        service,
        "get_po_or_404",
        lambda **kwargs: po,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_or_404",
        lambda **kwargs: current_cost,
    )
    monkeypatch.setattr(
        service,
        "_get_purchase_order_cost_paid_base",
        lambda **kwargs: Decimal("2"),
    )
    monkeypatch.setattr(
        service,
        (
            "_prepare_purchase_order_"
            "cost_money_bundle"
        ),
        lambda **kwargs: money("12"),
    )

    result = (
        service
        .confirm_purchase_order_cost_actual(
            db=db,
            user=user(),
            po_id=15,
            cost_id=41,
            amount=Decimal("12"),
            currency_id=1,
        )
    )

    assert result.actual_amount == (
        Decimal("12")
    )
    assert result.actual_amount_base == (
        Decimal("12")
    )
    assert (
        result.actual_confirmed_by_user_id
        == 31
    )
    assert isinstance(
        result.actual_confirmed_at,
        datetime,
    )
    assert db.commits == 1


def test_purchase_cost_route_contract():
    app = FastAPI()
    app.include_router(cost_router)

    operations = {
        (
            method.upper(),
            path,
        )
        for path, definition
        in app.openapi()["paths"].items()
        for method in definition
        if method.lower()
        in {
            "get",
            "post",
            "patch",
            "delete",
        }
    }

    assert operations == {
        (
            "GET",
            "/purchase/orders/{po_id}/costs",
        ),
        (
            "POST",
            "/purchase/orders/{po_id}/costs",
        ),
        (
            "GET",
            (
                "/purchase/orders/{po_id}/"
                "costs/{cost_id}"
            ),
        ),
        (
            "PATCH",
            (
                "/purchase/orders/{po_id}/"
                "costs/{cost_id}"
            ),
        ),
        (
            "DELETE",
            (
                "/purchase/orders/{po_id}/"
                "costs/{cost_id}"
            ),
        ),
        (
            "POST",
            (
                "/purchase/orders/{po_id}/"
                "costs/{cost_id}/"
                "confirm-actual"
            ),
        ),
        (
            "GET",
            (
                "/purchase/orders/{po_id}/"
                "payment-summary"
            ),
        ),
    }


def test_cross_module_reads_use_services():
    purchase_source = (
        BACKEND_ROOT
        / "purchase_management"
        / "services.py"
    ).read_text(encoding="utf-8")

    finance_source = (
        BACKEND_ROOT
        / "financial_management"
        / "services.py"
    ).read_text(encoding="utf-8")

    assert (
        "from financial_management.models"
        not in purchase_source
    )
    assert (
        "from financial_management.services import"
        in purchase_source
    )
    assert (
        "from purchase_management.models"
        not in finance_source
    )
    assert (
        "from purchase_management.schemas"
        not in finance_source
    )
    assert (
        "from purchase_management.routes"
        not in finance_source
    )
