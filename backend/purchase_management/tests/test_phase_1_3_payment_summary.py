from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI


os.environ.setdefault(
    "POSTGRES_DB",
    "test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "localhost",
)
os.environ.setdefault(
    "default_username",
    "admin",
)
os.environ.setdefault(
    "default_password",
    "admin",
)
os.environ.setdefault(
    "default_firstname",
    "Admin",
)
os.environ.setdefault(
    "jwt_secret",
    "secret",
)
os.environ.setdefault(
    "openai_api_key",
    "test",
)
os.environ.setdefault(
    "jina_api_key",
    "test",
)

sys.path.insert(
    0,
    str(
        Path(__file__)
        .resolve()
        .parents[2]
    ),
)


from financial_management import services as finance_services  # noqa: E402
from purchase_management import services  # noqa: E402
from purchase_management.routes.costs import router  # noqa: E402


def user():
    return SimpleNamespace(
        id=31,
        company_id=7,
        role="user",
    )


def cost(
    *,
    cost_id: int,
    cost_type: str,
    predicted=None,
    actual=None,
):
    return SimpleNamespace(
        id=cost_id,
        cost_type=cost_type,
        predicted_amount_base=(
            Decimal(str(predicted))
            if predicted is not None
            else None
        ),
        actual_amount_base=(
            Decimal(str(actual))
            if actual is not None
            else None
        ),
    )


def purchase_order(costs):
    return SimpleNamespace(
        id=15,
        company_id=7,
        costs=list(costs),
    )


def base_currency():
    return SimpleNamespace(
        id=1,
        code="IRT",
        decimal_places=0,
        is_active=True,
    )


def patch_summary_dependencies(
    monkeypatch,
    *,
    po,
    paid,
    legacy=False,
):
    monkeypatch.setattr(
        services,
        "get_po_or_404",
        lambda **_kwargs: po,
    )

    monkeypatch.setattr(
        services,
        "_get_company_base_currency_reference",
        lambda **_kwargs: base_currency(),
    )

    monkeypatch.setattr(
        services,
        "_purchase_order_has_untracked_legacy_payments",
        lambda **_kwargs: legacy,
    )

    monkeypatch.setattr(
        finance_services,
        "get_purchase_cost_payment_summaries",
        lambda **_kwargs: paid,
    )


def test_tracked_payment_summary_calculations(
    monkeypatch,
):
    po = purchase_order(
        [
            cost(
                cost_id=1,
                cost_type="freight",
                predicted=100,
            ),
            cost(
                cost_id=2,
                cost_type="tax",
                predicted=50,
                actual=70,
            ),
            cost(
                cost_id=3,
                cost_type="other",
                actual=25,
            ),
            cost(
                cost_id=4,
                cost_type="insurance",
                predicted=40,
                actual=40,
            ),
        ]
    )

    patch_summary_dependencies(
        monkeypatch,
        po=po,
        paid={
            1: {
                "cost_id": 1,
                "paid_base": Decimal("20"),
            },
            2: {
                "cost_id": 2,
                "paid_base": Decimal("30"),
            },
            3: {
                "cost_id": 3,
                "paid_base": Decimal("25"),
            },
            4: {
                "cost_id": 4,
                "paid_base": Decimal("50"),
            },
        },
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    assert result[
        "purchase_order_id"
    ] == 15

    assert result[
        "base_currency_id"
    ] == 1

    assert result[
        "payment_tracking"
    ] == "tracked"

    assert result[
        "predicted_total_base"
    ] == Decimal("190")

    assert result[
        "predicted_by_cost_type_base"
    ] == {
        "goods": Decimal("0"),
        "freight": Decimal("100"),
        "customs": Decimal("0"),
        "tax": Decimal("50"),
        "insurance": Decimal("40"),
        "other": Decimal("0"),
    }

    assert result[
        "actual_total_base"
    ] == Decimal("135")

    assert result[
        "unpredicted_total_base"
    ] == Decimal("25")

    assert result[
        "paid_total_base"
    ] == Decimal("125")

    assert result[
        "outstanding_total_base"
    ] == Decimal("110")

    assert result[
        "variance_total_base"
    ] == Decimal("45")

    rows = {
        row["cost_id"]: row
        for row in result["costs"]
    }

    assert rows[1][
        "settlement_target_base"
    ] == Decimal("100")

    assert rows[1][
        "outstanding_base"
    ] == Decimal("80")

    assert rows[1][
        "variance_base"
    ] is None

    assert rows[1][
        "payment_state"
    ] == "advance_paid"

    assert rows[2][
        "settlement_target_base"
    ] == Decimal("70")

    assert rows[2][
        "outstanding_base"
    ] == Decimal("40")

    assert rows[2][
        "variance_base"
    ] == Decimal("20")

    assert rows[2][
        "payment_state"
    ] == "partially_paid"

    assert rows[3][
        "outstanding_base"
    ] == Decimal("0")

    assert rows[3][
        "variance_base"
    ] == Decimal("25")

    assert rows[3][
        "payment_state"
    ] == "paid"

    assert rows[4][
        "outstanding_base"
    ] == Decimal("-10")

    assert rows[4][
        "payment_state"
    ] == "payment_review_required"


def test_legacy_unallocated_links_disable_tracking(
    monkeypatch,
):
    po = purchase_order(
        [
            cost(
                cost_id=1,
                cost_type="freight",
                predicted=100,
            ),
            cost(
                cost_id=2,
                cost_type="tax",
                predicted=20,
                actual=25,
            ),
        ]
    )

    patch_summary_dependencies(
        monkeypatch,
        po=po,
        paid={},
        legacy=True,
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    assert result[
        "payment_tracking"
    ] == "not_tracked"

    assert {
        row["payment_state"]
        for row in result["costs"]
    } == {
        "not_tracked"
    }

    assert result[
        "predicted_total_base"
    ] == Decimal("120")

    assert result[
        "actual_total_base"
    ] == Decimal("25")

    assert result[
        "paid_total_base"
    ] == Decimal("0")


def test_missing_finance_rows_are_unpaid(
    monkeypatch,
):
    po = purchase_order(
        [
            cost(
                cost_id=10,
                cost_type="customs",
                predicted=75,
            )
        ]
    )

    patch_summary_dependencies(
        monkeypatch,
        po=po,
        paid={},
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    row = result["costs"][0]

    assert row[
        "paid_base"
    ] == Decimal("0")

    assert row[
        "outstanding_base"
    ] == Decimal("75")

    assert row[
        "payment_state"
    ] == "unpaid"


def test_zero_actual_cost_is_paid_without_payment(
    monkeypatch,
):
    po = purchase_order(
        [
            cost(
                cost_id=20,
                cost_type="other",
                predicted=10,
                actual=0,
            )
        ]
    )

    patch_summary_dependencies(
        monkeypatch,
        po=po,
        paid={},
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    row = result["costs"][0]

    assert row[
        "settlement_target_base"
    ] == Decimal("0")

    assert row[
        "payment_state"
    ] == "paid"

    assert row[
        "variance_base"
    ] == Decimal("-10")


def test_empty_purchase_order_summary(
    monkeypatch,
):
    po = purchase_order([])

    patch_summary_dependencies(
        monkeypatch,
        po=po,
        paid={},
    )

    result = (
        services.get_purchase_order_payment_summary(
            db=object(),
            user=user(),
            po_id=15,
        )
    )

    assert result["costs"] == []

    assert result[
        "predicted_total_base"
    ] == Decimal("0")

    assert result[
        "actual_total_base"
    ] == Decimal("0")

    assert result[
        "paid_total_base"
    ] == Decimal("0")

    assert result[
        "outstanding_total_base"
    ] == Decimal("0")

    assert result[
        "variance_total_base"
    ] == Decimal("0")


def test_payment_summary_openapi_contract():
    app = FastAPI()
    app.include_router(router)

    path = (
        "/purchase/orders/{po_id}/"
        "payment-summary"
    )

    operation = app.openapi()[
        "paths"
    ][path]["get"]

    assert (
        operation["responses"]["200"][
            "content"
        ][
            "application/json"
        ][
            "schema"
        ][
            "$ref"
        ]
        == (
            "#/components/schemas/"
            "PurchaseOrderPaymentSummaryRead"
        )
    )

    assert (
        operation["operationId"]
        == (
            "get_payment_summary_"
            "purchase_orders__po_id__"
            "payment_summary_get"
        )
    )
