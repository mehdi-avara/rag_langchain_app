from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


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


from core.exceptions.error_codes import (  # noqa: E402
    FINANCIAL_RECEIPT_BASE_CURRENCY_NOT_CONFIGURED,
    FINANCIAL_RECEIPT_EXCHANGE_RATE_NOT_FOUND,
)
from financial_management import services  # noqa: E402
from financial_management.models import (  # noqa: E402
    FinancialCard,
    FinancialCurrency,
    FinancialDirection,
    FinancialReceipt,
)
from financial_management.routes import (  # noqa: E402
    receipts as receipt_routes,
)
from financial_management.schemas import (  # noqa: E402
    FinancialReceiptCreate,
    FinancialReceiptUpdate,
    PurchaseCostPaymentAllocationCreate,
)


def currency(
    *,
    currency_id: int,
    code: str,
    decimal_places: int,
    active: bool = True,
):
    return SimpleNamespace(
        id=currency_id,
        code=code,
        decimal_places=decimal_places,
        is_active=active,
    )


def canonical_fields(
    *,
    amount=Decimal("100"),
    currency_id: int = 1,
    currency_code: str = "IRT",
    base_currency_id: int = 1,
    base_currency_code: str = "IRT",
    rate=Decimal("1"),
):
    amount_value = Decimal(str(amount))
    rate_value = Decimal(str(rate))
    amount_base = amount_value * rate_value

    return {
        "amount": amount_value,
        "currency": currency_code,
        "base_currency": base_currency_code,
        "exchange_rate_to_base": rate_value,
        "base_amount": amount_base,
        "exchange_rate_source": (
            "system"
            if rate_value == Decimal("1")
            else "manual"
        ),
        "currency_id": currency_id,
        "base_currency_id": (
            base_currency_id
        ),
        "amount_base": amount_base,
        "exchange_rate_used": rate_value,
    }


class QueryStub:
    def __init__(
        self,
        first_row=None,
    ):
        self.first_row = first_row

    def filter(
        self,
        *_args,
        **_kwargs,
    ):
        return self

    def first(self):
        return self.first_row


class CompanyDB:
    def __init__(
        self,
        company,
    ):
        self.company = company

    def query(
        self,
        _model,
    ):
        return QueryStub(
            first_row=self.company
        )


class RouteDB:
    def __init__(self):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.refresh_count = 0
        self._next_id = 100

    def add(
        self,
        value,
    ):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1

        for value in self.added:
            if (
                getattr(
                    value,
                    "id",
                    None,
                )
                is None
            ):
                value.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def refresh(
        self,
        value,
    ):
        self.refresh_count += 1

        if (
            getattr(
                value,
                "id",
                None,
            )
            is None
        ):
            value.id = self._next_id
            self._next_id += 1

        if (
            getattr(
                value,
                "created_at",
                None,
            )
            is None
        ):
            value.created_at = datetime(
                2026,
                7,
                27,
                10,
                0,
                0,
            )

        if (
            getattr(
                value,
                "updated_at",
                None,
            )
            is None
        ):
            value.updated_at = (
                value.created_at
            )


def current_user():
    return SimpleNamespace(
        id=9,
        company_id=1,
        role="user",
    )


def build_card():
    card = FinancialCard(
        id=7,
        company_id=1,
        owner_id=9,
        title="Main Card",
        card_number="6037991234567890",
        bank_name="Melli",
        account_owner_name="Mehdi",
        description=None,
        is_active=True,
    )

    card.created_at = datetime(
        2026,
        7,
        27,
        8,
        0,
        0,
    )

    card.updated_at = card.created_at

    return card


def build_receipt():
    card = build_card()

    receipt = FinancialReceipt(
        id=11,
        company_id=1,
        owner_id=9,
        credit_card_id=card.id,
        customer_id=None,
        description="Supplier payment",
        description_embedding=None,
        tracking_number=None,
        amount=Decimal("10.00"),
        currency="USD",
        base_currency="IRT",
        exchange_rate_to_base=Decimal(
            "500000"
        ),
        base_amount=Decimal(
            "5000000"
        ),
        exchange_rate_source="manual",
        currency_id=3,
        base_currency_id=1,
        amount_base=Decimal(
            "5000000"
        ),
        exchange_rate_used=Decimal(
            "500000"
        ),
        direction=(
            FinancialDirection.OUTPUT
        ),
        counterparty_name="Supplier",
        receipt_date=datetime(
            2026,
            7,
            27,
            9,
            0,
            0,
        ),
    )

    receipt.credit_card = card
    receipt.customer = None
    receipt.files = []
    receipt.created_at = datetime(
        2026,
        7,
        27,
        9,
        5,
        0,
    )
    receipt.updated_at = (
        receipt.created_at
    )

    return receipt


def test_missing_company_base_currency_is_catalogued():
    db = CompanyDB(
        SimpleNamespace(
            id=1,
            base_currency_id=None,
        )
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        services._company_base_currency_record(
            db=db,
            current_user=current_user(),
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == FINANCIAL_RECEIPT_BASE_CURRENCY_NOT_CONFIGURED
    )


def test_default_currency_uses_company_base(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    result = (
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("1250.6"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
        )
    )

    assert result["amount"] == Decimal(
        "1251"
    )
    assert result["currency_id"] == 1
    assert result["base_currency_id"] == 1
    assert (
        result["exchange_rate_used"]
        == Decimal("1.0000000000")
    )
    assert result["amount_base"] == Decimal(
        "1251"
    )


def test_database_rate_is_resolved_and_frozen(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    selected = currency(
        currency_id=3,
        code="USD",
        decimal_places=2,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    monkeypatch.setattr(
        services,
        "get_currency_or_404",
        lambda **_kwargs: selected,
    )

    captured = {}

    def fake_get_rate(
        **kwargs,
    ):
        captured.update(kwargs)
        return Decimal("500000")

    monkeypatch.setattr(
        services,
        "get_rate",
        fake_get_rate,
    )

    receipt_date = datetime(
        2026,
        7,
        27,
        9,
        30,
        0,
    )

    result = (
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("10.25"),
            receipt_date=receipt_date,
            currency_id=3,
        )
    )

    assert captured["from_code"] == "USD"
    assert captured["to_code"] == "IRT"
    assert (
        captured["on_date"]
        == receipt_date.date()
    )

    assert result["amount"] == Decimal(
        "10.25"
    )
    assert (
        result["exchange_rate_used"]
        == Decimal(
            "500000.0000000000"
        )
    )
    assert result["amount_base"] == Decimal(
        "5125000"
    )
    assert (
        result["exchange_rate_source"]
        == "system"
    )


def test_manual_rate_is_frozen(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    selected = currency(
        currency_id=3,
        code="USD",
        decimal_places=2,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    monkeypatch.setattr(
        services,
        "get_currency_or_404",
        lambda **_kwargs: selected,
    )

    monkeypatch.setattr(
        services,
        "get_rate",
        lambda **_kwargs: pytest.fail(
            "Database rate must not be read "
            "when a manual rate is supplied"
        ),
    )

    result = (
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("2.50"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
            currency_id=3,
            exchange_rate_used=Decimal(
                "480000"
            ),
        )
    )

    assert (
        result["exchange_rate_used"]
        == Decimal(
            "480000.0000000000"
        )
    )
    assert result["amount_base"] == Decimal(
        "1200000"
    )
    assert (
        result["exchange_rate_source"]
        == "manual"
    )


def test_missing_database_rate_is_catalogued(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    selected = currency(
        currency_id=3,
        code="USD",
        decimal_places=2,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    monkeypatch.setattr(
        services,
        "get_currency_or_404",
        lambda **_kwargs: selected,
    )

    monkeypatch.setattr(
        services,
        "get_rate",
        lambda **_kwargs: None,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("10"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
            currency_id=3,
        )

    assert exc.value.status_code == 422
    assert (
        exc.value.detail["code"]
        == FINANCIAL_RECEIPT_EXCHANGE_RATE_NOT_FOUND
    )


def test_currency_id_and_legacy_code_mismatch_is_rejected(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    selected = currency(
        currency_id=3,
        code="USD",
        decimal_places=2,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    monkeypatch.setattr(
        services,
        "get_currency_or_404",
        lambda **_kwargs: selected,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("10"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
            currency_id=3,
            currency_code=(
                FinancialCurrency.DIRHAM
            ),
        )

    assert exc.value.status_code == 422
    assert (
        "different currencies"
        in str(exc.value.detail)
    )


def test_same_currency_non_unit_rate_is_rejected(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("100"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
            exchange_rate_used=Decimal(
                "2"
            ),
        )

    assert exc.value.status_code == 422
    assert (
        "must be 1"
        in str(exc.value.detail)
    )


def test_inactive_selected_currency_is_rejected(
    monkeypatch,
):
    base = currency(
        currency_id=1,
        code="IRT",
        decimal_places=0,
    )

    selected = currency(
        currency_id=3,
        code="USD",
        decimal_places=2,
        active=False,
    )

    monkeypatch.setattr(
        services,
        "_company_base_currency_record",
        lambda **_kwargs: base,
    )

    monkeypatch.setattr(
        services,
        "get_currency_or_404",
        lambda **_kwargs: selected,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        services.resolve_receipt_money_fields(
            db=object(),
            current_user=current_user(),
            amount=Decimal("10"),
            receipt_date=datetime(
                2026,
                7,
                27,
                9,
                0,
                0,
            ),
            currency_id=3,
        )

    assert exc.value.status_code == 422
    assert (
        "must be active"
        in str(exc.value.detail)
    )


def test_create_receipt_persists_complete_canonical_bundle(
    monkeypatch,
):
    db = RouteDB()
    card = build_card()

    monkeypatch.setattr(
        receipt_routes,
        "get_card_or_404",
        lambda *_args, **_kwargs: card,
    )

    monkeypatch.setattr(
        receipt_routes,
        "safe_embed_text",
        lambda *_args, **_kwargs: None,
    )

    money = canonical_fields(
        amount=Decimal("100"),
    )

    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        lambda **_kwargs: money,
    )

    monkeypatch.setattr(
        receipt_routes,
        "receipt_to_out",
        lambda receipt: receipt,
    )

    payload = FinancialReceiptCreate(
        description="Normal payment",
        amount=Decimal("100"),
        direction=(
            FinancialDirection.OUTPUT
        ),
        counterparty_name="Supplier",
        receipt_date=datetime(
            2026,
            7,
            27,
            10,
            0,
            0,
        ),
        credit_card_id=card.id,
    )

    result = receipt_routes.create_receipt(
        payload=payload,
        db=db,
        current_user=current_user(),
    )

    assert result.currency_id == 1
    assert result.base_currency_id == 1
    assert result.amount_base == Decimal(
        "100"
    )
    assert (
        result.exchange_rate_used
        == Decimal("1")
    )

    assert db.commit_count == 1
    assert db.rollback_count == 0
    assert db.flush_count == 0
    assert db.refresh_count == 1


def test_embedded_allocations_use_same_transaction(
    monkeypatch,
):
    db = RouteDB()
    card = build_card()
    calls = {}

    monkeypatch.setattr(
        receipt_routes,
        "get_card_or_404",
        lambda *_args, **_kwargs: card,
    )

    monkeypatch.setattr(
        receipt_routes,
        "safe_embed_text",
        lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        lambda **_kwargs: canonical_fields(
            amount=Decimal("100")
        ),
    )

    monkeypatch.setattr(
        receipt_routes,
        "receipt_to_out",
        lambda receipt: receipt,
    )

    def create_allocations(
        **kwargs,
    ):
        calls.update(kwargs)
        return []

    monkeypatch.setattr(
        receipt_routes,
        "create_purchase_cost_allocations",
        create_allocations,
    )

    allocation = (
        PurchaseCostPaymentAllocationCreate(
            purchase_order_cost_id=15,
            allocated_amount=Decimal(
                "100"
            ),
        )
    )

    payload = FinancialReceiptCreate(
        description="Freight payment",
        amount=Decimal("100"),
        direction=(
            FinancialDirection.OUTPUT
        ),
        counterparty_name="Supplier",
        receipt_date=datetime(
            2026,
            7,
            27,
            10,
            0,
            0,
        ),
        credit_card_id=card.id,
        purchase_cost_allocations=[
            allocation
        ],
    )

    receipt = receipt_routes.create_receipt(
        payload=payload,
        db=db,
        current_user=current_user(),
    )

    assert receipt.id == 100
    assert db.flush_count == 1
    assert db.commit_count == 1
    assert db.rollback_count == 0

    assert calls["db"] is db
    assert calls["receipt_id"] == 100
    assert calls["commit"] is False
    assert calls["allocations"] == [
        allocation
    ]


def test_embedded_allocation_failure_rolls_back_receipt(
    monkeypatch,
):
    db = RouteDB()
    card = build_card()

    monkeypatch.setattr(
        receipt_routes,
        "get_card_or_404",
        lambda *_args, **_kwargs: card,
    )

    monkeypatch.setattr(
        receipt_routes,
        "safe_embed_text",
        lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        lambda **_kwargs: canonical_fields(
            amount=Decimal("100")
        ),
    )

    def fail_allocations(
        **_kwargs,
    ):
        raise HTTPException(
            status_code=422,
            detail="allocation rejected",
        )

    monkeypatch.setattr(
        receipt_routes,
        "create_purchase_cost_allocations",
        fail_allocations,
    )

    payload = FinancialReceiptCreate(
        description="Freight payment",
        amount=Decimal("100"),
        direction=(
            FinancialDirection.OUTPUT
        ),
        counterparty_name="Supplier",
        receipt_date=datetime(
            2026,
            7,
            27,
            10,
            0,
            0,
        ),
        credit_card_id=card.id,
        purchase_cost_allocations=[
            PurchaseCostPaymentAllocationCreate(
                purchase_order_cost_id=15,
                allocated_amount=Decimal(
                    "100"
                ),
            )
        ],
    )

    with pytest.raises(
        HTTPException
    ):
        receipt_routes.create_receipt(
            payload=payload,
            db=db,
            current_user=current_user(),
        )

    assert db.flush_count == 1
    assert db.commit_count == 0
    assert db.rollback_count == 1


def test_amount_only_update_reuses_frozen_currency_context(
    monkeypatch,
):
    db = RouteDB()
    receipt = build_receipt()
    captured = {}

    monkeypatch.setattr(
        receipt_routes,
        "get_receipt_or_404",
        lambda *_args, **_kwargs: receipt,
    )

    monkeypatch.setattr(
        receipt_routes,
        "assert_receipt_financial_edit_allowed",
        lambda **_kwargs: None,
    )

    def resolve_fields(
        **kwargs,
    ):
        captured.update(kwargs)

        return canonical_fields(
            amount=kwargs["amount"],
            currency_id=3,
            currency_code="USD",
            rate=Decimal("500000"),
        )

    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        resolve_fields,
    )

    monkeypatch.setattr(
        receipt_routes,
        "receipt_to_out",
        lambda value: value,
    )

    result = receipt_routes.update_receipt(
        receipt_id=receipt.id,
        payload=FinancialReceiptUpdate(
            amount=Decimal("20")
        ),
        db=db,
        current_user=current_user(),
    )

    assert captured["amount"] == Decimal(
        "20"
    )
    assert captured["currency_id"] == 3
    assert (
        captured["exchange_rate_used"]
        == Decimal("500000")
    )
    assert captured["currency_code"] is None

    assert result.amount == Decimal("20")
    assert result.amount_base == Decimal(
        "10000000"
    )
    assert db.commit_count == 1
    assert db.rollback_count == 0


def test_legacy_currency_update_resolves_new_currency(
    monkeypatch,
):
    db = RouteDB()
    receipt = build_receipt()
    captured = {}

    monkeypatch.setattr(
        receipt_routes,
        "get_receipt_or_404",
        lambda *_args, **_kwargs: receipt,
    )

    monkeypatch.setattr(
        receipt_routes,
        "assert_receipt_financial_edit_allowed",
        lambda **_kwargs: None,
    )

    def resolve_fields(
        **kwargs,
    ):
        captured.update(kwargs)

        return canonical_fields(
            amount=kwargs["amount"],
            currency_id=4,
            currency_code="AED",
            rate=Decimal("140000"),
        )

    monkeypatch.setattr(
        receipt_routes,
        "resolve_receipt_money_fields",
        resolve_fields,
    )

    monkeypatch.setattr(
        receipt_routes,
        "receipt_to_out",
        lambda value: value,
    )

    receipt_routes.update_receipt(
        receipt_id=receipt.id,
        payload=FinancialReceiptUpdate(
            currency=(
                FinancialCurrency.DIRHAM
            )
        ),
        db=db,
        current_user=current_user(),
    )

    assert captured["currency_id"] is None
    assert (
        captured["currency_code"]
        == FinancialCurrency.DIRHAM
    )
    assert (
        captured["exchange_rate_used"]
        is None
    )


def test_receipt_serializer_exposes_canonical_fields():
    receipt = build_receipt()

    result = services.receipt_to_out(
        receipt
    )

    assert result.currency_id == 3
    assert result.base_currency_id == 1
    assert result.amount_base == Decimal(
        "5000000"
    )
    assert (
        result.exchange_rate_used
        == Decimal("500000")
    )


def test_receipt_openapi_exposes_canonical_create_contract():
    from api import app

    openapi = app.openapi()

    operation = openapi["paths"][
        "/financial_management/receipts"
    ]["post"]

    assert "201" in operation["responses"]

    create_schema = openapi[
        "components"
    ][
        "schemas"
    ][
        "FinancialReceiptCreate"
    ]

    properties = create_schema[
        "properties"
    ]

    assert "currency_id" in properties
    assert "exchange_rate_used" in properties
    assert (
        "purchase_cost_allocations"
        in properties
    )

    output_schema = openapi[
        "components"
    ][
        "schemas"
    ][
        "FinancialReceiptOut"
    ]

    output_properties = output_schema[
        "properties"
    ]

    assert "currency_id" in output_properties
    assert (
        "base_currency_id"
        in output_properties
    )
    assert "amount_base" in output_properties
    assert (
        "exchange_rate_used"
        in output_properties
    )
