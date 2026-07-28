from __future__ import annotations

import os
from datetime import (
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api import app
from db.init_db import SessionLocal
from deps import require_permission
from Models import (
    Company,
    Currency,
    ExchangeRate,
    FinancialCard,
    Item,
    Supplier,
    User,
)
from financial_management.models import (
    FinancialDirection,
    FinancialReceipt,
    PurchaseCostPaymentAllocation,
)
from financial_management.routes import (
    receipts as receipt_routes,
)
from financial_management.schemas import (
    FinancialReceiptCreate,
    PurchaseCostPaymentAllocationCreate,
)
from purchase_management import (
    services as purchase_services,
)
from purchase_management.models import (
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderCost,
    PurchaseOrderStatus,
)
from shared.currency.services import (
    quantize_money,
)


RUN_DATABASE_SCENARIO = (
    os.getenv(
        "RUN_PHASE1_NEGATIVE_CONTROLS_E2E"
    )
    == "1"
)


def decimal(value) -> Decimal:
    return Decimal(str(value))


def create_payment_receipt(
    *,
    db,
    current_user,
    card,
    supplier,
    currency,
    exchange_rate,
    cost,
    amount,
    description,
):
    payload = FinancialReceiptCreate(
        description=description,
        amount=amount,
        currency_id=currency.id,
        exchange_rate_used=exchange_rate,
        direction=FinancialDirection.OUTPUT,
        counterparty_name=supplier.name,
        receipt_date=datetime.utcnow(),
        credit_card_id=card.id,
        purchase_cost_allocations=[
            PurchaseCostPaymentAllocationCreate(
                purchase_order_cost_id=cost.id,
                allocated_amount=amount,
            )
        ],
    )

    return receipt_routes.create_receipt(
        payload=payload,
        db=db,
        current_user=current_user,
    )


def test_negative_control_route_and_rbac_contract():
    paths = app.openapi()["paths"]

    order_path = paths[
        "/purchase/orders/{po_id}"
    ]

    assert "delete" in order_path

    assert (
        order_path["delete"]["responses"].keys()
        >= {
            "204",
            "422",
        }
    )

    route_source = Path(
        "purchase_management/routes/orders.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "purchase_management:orders:delete"
        in route_source
    )

    limited_user = SimpleNamespace(
        id=900001,
        company_id=900001,
        role="user",
        roles=[
            SimpleNamespace(
                is_active=True,
                permissions=[],
            )
        ],
    )

    checker = require_permission(
        "purchase_management:orders:delete"
    )

    with pytest.raises(
        HTTPException
    ) as error:
        checker(limited_user)

    assert error.value.status_code == 403
    assert error.value.detail == (
        "Permission denied"
    )


@pytest.mark.skipif(
    not RUN_DATABASE_SCENARIO,
    reason=(
        "Set RUN_PHASE1_NEGATIVE_CONTROLS_E2E=1 "
        "and use a disposable migrated database"
    ),
)
def test_cancellation_paid_cost_and_tenant_controls():
    db = SessionLocal()
    marker = uuid4().hex[:10]

    run_label = (
        f"E2E negative controls {marker}"
    )

    try:
        card = (
            db.query(FinancialCard)
            .join(
                User,
                User.id
                == FinancialCard.owner_id,
            )
            .filter(
                FinancialCard.is_active.is_(True),
                User.is_active.is_(True),
                User.company_id
                == FinancialCard.company_id,
            )
            .order_by(
                FinancialCard.id
            )
            .first()
        )

        assert card is not None

        current_user = (
            db.query(User)
            .filter(
                User.id == card.owner_id
            )
            .one()
        )

        company = (
            db.query(Company)
            .filter(
                Company.id
                == current_user.company_id
            )
            .one()
        )

        assert company.base_currency_id is not None
        assert company.allow_self_approval is True

        base_currency = (
            db.query(Currency)
            .filter(
                Currency.id
                == company.base_currency_id,
                Currency.is_active.is_(True),
            )
            .one()
        )

        quote_currency = (
            db.query(Currency)
            .filter(
                Currency.code == "AED",
                Currency.is_active.is_(True),
            )
            .one()
        )

        template_item = (
            db.query(Item)
            .filter(
                Item.company_id
                == company.id,
                Item.category_id.is_not(None),
                Item.unit_id.is_not(None),
                Item.is_active.is_(True),
            )
            .order_by(
                Item.id
            )
            .first()
        )

        assert template_item is not None

        item = Item(
            company_id=company.id,
            item_code=(
                f"E2E-NEG-ITEM-{marker}"
            ),
            name=(
                f"E2E Negative Controls Item "
                f"{marker}"
            ),
            description=run_label,
            category_id=(
                template_item.category_id
            ),
            unit_id=template_item.unit_id,
            specs={},
            item_type=(
                template_item.item_type
                or "material"
            ),
            is_active=True,
            is_critical=False,
            created_by_user_id=(
                current_user.id
            ),
        )

        supplier = Supplier(
            company_id=company.id,
            code=(
                f"E2E-NEG-SUP-{marker}"
            ),
            name=(
                f"E2E Negative Controls Supplier "
                f"{marker}"
            ),
            supplier_type="local",
            country="Iran",
            status="approved",
            notes=run_label,
            created_by_user_id=(
                current_user.id
            ),
        )

        db.add_all(
            [
                item,
                supplier,
            ]
        )
        db.commit()
        db.refresh(item)
        db.refresh(supplier)

        today = date.today()

        rate_row = (
            db.query(ExchangeRate)
            .filter(
                ExchangeRate.from_currency_id
                == quote_currency.id,
                ExchangeRate.to_currency_id
                == base_currency.id,
                ExchangeRate.effective_date
                <= today,
            )
            .order_by(
                ExchangeRate.effective_date.desc(),
                ExchangeRate.id.desc(),
            )
            .first()
        )

        if rate_row is None:
            rate_row = ExchangeRate(
                from_currency_id=(
                    quote_currency.id
                ),
                to_currency_id=(
                    base_currency.id
                ),
                rate=Decimal("500000"),
                effective_date=today,
                source=f"e2e-{marker}",
                created_by_user_id=(
                    current_user.id
                ),
            )

            db.add(rate_row)
            db.commit()
            db.refresh(rate_row)

        exchange_rate = decimal(
            rate_row.rate
        )

        def create_order(
            *,
            title_suffix: str,
            unit_price: Decimal,
        ):
            return (
                purchase_services
                .create_purchase_order(
                    db=db,
                    user=current_user,
                    data={
                        "title": (
                            f"{run_label} "
                            f"{title_suffix}"
                        ),
                        "supplier_id": supplier.id,
                        "description": run_label,
                        "expected_delivery_date": (
                            datetime.utcnow()
                            + timedelta(days=15)
                        ),
                        "lines": [
                            {
                                "item_id": item.id,
                                "ordered_quantity": (
                                    Decimal("2")
                                ),
                                "unit_id": item.unit_id,
                                "line_description": (
                                    run_label
                                ),
                                "unit_price": unit_price,
                                "currency_id": (
                                    quote_currency.id
                                ),
                                "exchange_rate_used": (
                                    exchange_rate
                                ),
                                "notes": run_label,
                            }
                        ],
                    },
                )
            )

        cancelled_order = create_order(
            title_suffix="cancelled",
            unit_price=Decimal("100"),
        )

        assert cancelled_order.status == (
            PurchaseOrderStatus
            .DRAFT
            .value
        )

        assert (
            cancelled_order.approval_status
            == PurchaseApprovalStatus
            .DRAFT
            .value
        )

        cancelled_order = (
            purchase_services
            .cancel_purchase_order(
                db=db,
                user=current_user,
                po_id=cancelled_order.id,
            )
        )

        assert cancelled_order.status == (
            PurchaseOrderStatus
            .CANCELLED
            .value
        )

        with pytest.raises(
            HTTPException
        ) as cancelled_edit_error:
            (
                purchase_services
                .update_purchase_order(
                    db=db,
                    user=current_user,
                    po_id=cancelled_order.id,
                    description=(
                        "This must not be saved"
                    ),
                )
            )

        assert (
            cancelled_edit_error
            .value
            .status_code
            == 422
        )

        assert (
            cancelled_edit_error
            .value
            .detail["code"]
            == (
                "PURCHASE_ORDER_"
                "COMMERCIAL_FIELDS_IMMUTABLE"
            )
        )

        db.expire_all()

        persisted_cancelled = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.id
                == cancelled_order.id
            )
            .one()
        )

        assert persisted_cancelled.status == (
            PurchaseOrderStatus
            .CANCELLED
            .value
        )

        assert persisted_cancelled.description == (
            run_label
        )

        paid_order = create_order(
            title_suffix="paid",
            unit_price=Decimal("120"),
        )

        paid_order = (
            purchase_services.process_approval(
                db=db,
                user=current_user,
                po_id=paid_order.id,
                action="submit",
                note=run_label,
            )
        )

        paid_order = (
            purchase_services.process_approval(
                db=db,
                user=current_user,
                po_id=paid_order.id,
                action="approve",
                note=run_label,
            )
        )

        assert paid_order.status == (
            PurchaseOrderStatus
            .ORDERED
            .value
        )

        assert (
            paid_order.approval_status
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        goods_cost = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost
                .purchase_order_id
                == paid_order.id,
                PurchaseOrderCost.cost_type
                == "goods",
            )
            .one()
        )

        assert goods_cost.predicted_amount is not None

        payment_amount = Decimal("50")

        receipt = create_payment_receipt(
            db=db,
            current_user=current_user,
            card=card,
            supplier=supplier,
            currency=quote_currency,
            exchange_rate=exchange_rate,
            cost=goods_cost,
            amount=payment_amount,
            description=run_label,
        )

        assert receipt.id is not None

        allocation = (
            db.query(
                PurchaseCostPaymentAllocation
            )
            .filter(
                PurchaseCostPaymentAllocation
                .financial_receipt_id
                == receipt.id,
                PurchaseCostPaymentAllocation
                .purchase_order_cost_id
                == goods_cost.id,
            )
            .one()
        )

        expected_paid_base = quantize_money(
            payment_amount
            * exchange_rate,
            base_currency.decimal_places,
        )

        assert decimal(
            allocation.allocated_amount
        ) == payment_amount

        assert decimal(
            allocation.allocated_amount_base
        ) == expected_paid_base

        with pytest.raises(
            HTTPException
        ) as paid_delete_error:
            purchase_services.delete_cost(
                db=db,
                user=current_user,
                po_id=paid_order.id,
                cost_id=goods_cost.id,
            )

        assert (
            paid_delete_error
            .value
            .status_code
            == 422
        )

        assert (
            paid_delete_error
            .value
            .detail["code"]
            == (
                "PURCHASE_ORDER_"
                "COST_HAS_PAYMENTS"
            )
        )

        assert (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost.id
                == goods_cost.id
            )
            .count()
            == 1
        )

        cross_tenant_user = SimpleNamespace(
            id=current_user.id,
            company_id=(
                company.id + 1000000
            ),
            role="user",
            roles=[],
        )

        with pytest.raises(
            HTTPException
        ) as cross_tenant_error:
            purchase_services.get_po_or_404(
                db=db,
                po_id=paid_order.id,
                user=cross_tenant_user,
            )

        assert (
            cross_tenant_error
            .value
            .status_code
            == 404
        )

        assert (
            cross_tenant_error
            .value
            .detail["code"]
            == "PURCHASE_ORDER_NOT_FOUND"
        )

        assert (
            db.query(FinancialReceipt)
            .filter(
                FinancialReceipt.id
                == receipt.id
            )
            .count()
            == 1
        )

        assert (
            db.query(
                PurchaseCostPaymentAllocation
            )
            .filter(
                PurchaseCostPaymentAllocation
                .id
                == allocation.id
            )
            .count()
            == 1
        )

        print()
        print(
            "NEGATIVE-CONTROL REFERENCES"
        )
        print(
            "CANCELLED PO:",
            cancelled_order.reference_number,
        )
        print(
            "PAID PO:",
            paid_order.reference_number,
        )
        print(
            "GOODS COST:",
            goods_cost.id,
        )
        print(
            "PAYMENT RECEIPT:",
            receipt.id,
        )
        print(
            "PAYMENT ALLOCATION:",
            allocation.id,
        )
        print(
            "PAYMENT:",
            payment_amount,
            quote_currency.code,
        )
        print(
            "PAID BASE:",
            expected_paid_base,
            base_currency.code,
        )
        print(
            "CANCELLED EDIT:",
            (
                "PURCHASE_ORDER_"
                "COMMERCIAL_FIELDS_IMMUTABLE"
            ),
        )
        print(
            "PAID DELETE:",
            (
                "PURCHASE_ORDER_"
                "COST_HAS_PAYMENTS"
            ),
        )
        print(
            "CROSS TENANT:",
            "PURCHASE_ORDER_NOT_FOUND",
        )
        print(
            "NEGATIVE CONTROLS: PASSED"
        )

    finally:
        db.close()
