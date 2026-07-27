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


from financial_management import (  # noqa: E402
    purchase_cost_allocation_service
    as service,
)


def current_user():
    return SimpleNamespace(
        id=1,
        company_id=1,
    )


def receipt():
    return SimpleNamespace(
        id=10,
        company_id=1,
        currency_id=4,
        base_currency_id=1,
        exchange_rate_used=Decimal("1"),
    )


def patch_dependencies(monkeypatch):
    monkeypatch.setattr(
        service,
        "_lock_cost",
        lambda **_kwargs: None,
    )

    monkeypatch.setattr(
        service,
        "_purchase_cost_reference",
        lambda **_kwargs: {
            "cost_id": 20,
            "company_id": 1,
            "supplier_id": 9,
            "target_currency_id": 4,
            "target_amount_base": (
                Decimal("100")
            ),
        },
    )

    monkeypatch.setattr(
        service,
        "get_currency_or_404",
        lambda *,
        db,
        currency_id: (
            SimpleNamespace(
                id=4,
                decimal_places=2,
            )
            if currency_id == 4
            else SimpleNamespace(
                id=1,
                decimal_places=0,
            )
        ),
    )


def test_allocation_rejects_zero_base_after_rounding(
    monkeypatch,
):
    patch_dependencies(monkeypatch)

    with pytest.raises(
        HTTPException
    ) as error:
        service._prepare_allocation(
            db=object(),
            current_user=current_user(),
            receipt=receipt(),
            purchase_order_cost_id=20,
            allocated_amount=Decimal(
                "0.01"
            ),
            currency_id=None,
            exchange_rate_used=None,
        )

    assert error.value.status_code == 422

    assert error.value.detail["code"] == (
        "FINANCIAL_RECEIPT_"
        "ALLOCATION_AMOUNT_TOO_SMALL"
    )

    assert (
        error.value.detail["message"]
        == (
            "Allocated amount is too small "
            "after base-currency conversion"
        )
    )


def test_allocation_accepts_positive_base_after_rounding(
    monkeypatch,
):
    patch_dependencies(monkeypatch)

    values, reference = (
        service._prepare_allocation(
            db=object(),
            current_user=current_user(),
            receipt=receipt(),
            purchase_order_cost_id=20,
            allocated_amount=Decimal("1"),
            currency_id=None,
            exchange_rate_used=None,
        )
    )

    assert values[
        "allocated_amount"
    ] == Decimal("1.00")

    assert values[
        "allocated_amount_base"
    ] == Decimal("1")

    assert reference["cost_id"] == 20
