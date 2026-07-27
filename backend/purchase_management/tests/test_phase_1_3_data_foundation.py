from pathlib import Path

from Models import (
    FinancialReceipt,
    PurchaseCostPaymentAllocation,
)
from core.exceptions import error_codes
from financial_management.permissions import (
    PERMISSIONS as FINANCE_PERMISSIONS,
)
from financial_management.schemas import (
    FinancialReceiptCreate,
    PurchaseCostPaymentAllocationCreate,
    PurchaseCostPaymentAllocationRead,
)
from purchase_management.models import (
    PurchaseCostType,
    PurchaseOrderCost,
    PurchaseOrderReceiptLink,
)
from purchase_management.permissions import (
    PERMISSIONS as PURCHASE_PERMISSIONS,
)
from purchase_management.schemas import (
    PurchaseOrderCostConfirmActual,
    PurchaseOrderPaymentSummaryRead,
)


def test_phase_1_3_cost_model_foundation():
    columns = {
        column.name
        for column
        in PurchaseOrderCost.__table__.columns
    }

    assert {
        "predicted_amount",
        "predicted_currency_id",
        "predicted_amount_base",
        "predicted_exchange_rate_used",
        "actual_amount",
        "actual_currency_id",
        "actual_amount_base",
        "actual_exchange_rate_used",
        "created_by_user_id",
        "actual_confirmed_at",
        "actual_confirmed_by_user_id",
    }.issubset(columns)

    assert PurchaseCostType.GOODS.value == "goods"

    link_columns = {
        column.name
        for column
        in PurchaseOrderReceiptLink
        .__table__
        .columns
    }

    assert "allocation_status" in link_columns


def test_phase_1_3_receipt_canonical_fields():
    columns = {
        column.name
        for column
        in FinancialReceipt.__table__.columns
    }

    assert {
        "currency_id",
        "base_currency_id",
        "amount_base",
        "exchange_rate_used",
    }.issubset(columns)


def test_phase_1_3_finance_allocation_model():
    assert (
        PurchaseCostPaymentAllocation
        .__tablename__
        == "purchase_cost_payment_allocations"
    )

    columns = {
        column.name
        for column
        in PurchaseCostPaymentAllocation
        .__table__
        .columns
    }

    assert columns == {
        "id",
        "company_id",
        "financial_receipt_id",
        "purchase_order_cost_id",
        "allocated_amount",
        "currency_id",
        "allocated_amount_base",
        "exchange_rate_used",
        "created_by_user_id",
        "created_at",
    }

    targets = {
        foreign_key.target_fullname
        for foreign_key
        in (
            PurchaseCostPaymentAllocation
            .__table__
            .c.purchase_order_cost_id
            .foreign_keys
        )
    }

    assert targets == {
        "purchase_order_costs.id"
    }


def test_phase_1_3_foundation_schemas():
    confirmation = (
        PurchaseOrderCostConfirmActual(
            amount="12.50",
            currency_id=3,
        )
    )

    assert str(confirmation.amount) == "12.50"
    assert confirmation.currency_id == 3

    allocation = (
        PurchaseCostPaymentAllocationCreate(
            purchase_order_cost_id=7,
            allocated_amount="5.25",
        )
    )

    assert allocation.currency_id is None
    assert allocation.exchange_rate_used is None

    receipt = FinancialReceiptCreate(
        description="Supplier payment",
        amount="10",
        direction="output",
        counterparty_name="Supplier",
        receipt_date="2026-07-27",
        credit_card_id=1,
        purchase_cost_allocations=[
            allocation,
        ],
    )

    assert len(
        receipt.purchase_cost_allocations
    ) == 1

    fields = (
        PurchaseCostPaymentAllocationRead
        .model_fields
    )

    assert "allocated_amount_base" in fields

    summary_fields = (
        PurchaseOrderPaymentSummaryRead
        .model_fields
    )

    assert "predicted_total_base" in (
        summary_fields
    )
    assert "outstanding_total_base" in (
        summary_fields
    )


def test_phase_1_3_permissions_registered():
    purchase_names = {
        permission[0]
        for permission in PURCHASE_PERMISSIONS
    }

    finance_names = {
        permission[0]
        for permission in FINANCE_PERMISSIONS
    }

    assert {
        "purchase_management:costs:read",
        "purchase_management:costs:manage",
        (
            "purchase_management:"
            "costs:confirm_actual"
        ),
        (
            "purchase_management:"
            "payment_summary:read"
        ),
    }.issubset(purchase_names)

    assert {
        (
            "financial_management:"
            "purchase_cost_allocations:read"
        ),
        (
            "financial_management:"
            "purchase_cost_allocations:create"
        ),
        (
            "financial_management:"
            "purchase_cost_allocations:delete"
        ),
    } == finance_names


def test_phase_1_3_error_codes_registered():
    required = {
        "PURCHASE_ORDER_COST_TYPE_INVALID",
        "PURCHASE_ORDER_COST_MONEY_INCOMPLETE",
        (
            "PURCHASE_ORDER_COST_"
            "NOT_FINANCIALLY_EDITABLE"
        ),
        "PURCHASE_ORDER_COST_ACTUAL_BELOW_PAID",
        "PURCHASE_ORDER_COST_HAS_PAYMENTS",
        (
            "FINANCIAL_RECEIPT_DIRECTION_"
            "INVALID_FOR_PURCHASE"
        ),
        (
            "FINANCIAL_RECEIPT_PURCHASE_"
            "COMPANY_MISMATCH"
        ),
        (
            "FINANCIAL_RECEIPT_ALLOCATION_"
            "EXCEEDS_RECEIPT"
        ),
        (
            "PURCHASE_ORDER_COST_ALLOCATION_"
            "EXCEEDS_COST"
        ),
        "FINANCIAL_RECEIPT_HAS_ALLOCATIONS",
        (
            "FINANCIAL_RECEIPT_BASE_"
            "CURRENCY_NOT_CONFIGURED"
        ),
        (
            "FINANCIAL_RECEIPT_"
            "EXCHANGE_RATE_NOT_FOUND"
        ),
    }

    for name in required:
        assert getattr(
            error_codes,
            name,
        ) == name


def test_phase_1_3_migration_contract():
    path = Path(
        "alembic/versions/"
        "13c0a1b2d3e4_"
        "add_po_cost_payment_foundation.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    assert (
        'revision: str = "13c0a1b2d3e4"'
        in source
    )
    assert (
        'down_revision: Union[str, None] = '
        '"d3e4f5a6b7c8"'
        in source
    )
    assert (
        "purchase_cost_payment_allocations"
        in source
    )
    assert "legacy_unallocated" in source
    assert "predicted_amount" in source
    assert "actual_amount" in source
