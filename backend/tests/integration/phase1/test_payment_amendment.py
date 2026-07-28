from __future__ import annotations

import os
from datetime import (
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api import app
from db.init_db import SessionLocal
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
import purchase_management.amendment_service as amendment_service
from purchase_management import (
    services as purchase_services,
)
from purchase_management.models import (
    PurchaseAmendmentStatus,
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderAmendment,
    PurchaseOrderCost,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhaseAllocation,
)
from shared.currency.services import (
    quantize_money,
)


RUN_DATABASE_SCENARIO = (
    os.getenv(
        "RUN_PHASE1_PAYMENT_AMENDMENT_E2E"
    )
    == "1"
)


def decimal(value) -> Decimal:
    return Decimal(str(value))


def payment_row(
    summary: dict,
    cost_id: int,
) -> dict:
    return {
        int(row["cost_id"]): row
        for row in summary["costs"]
    }[cost_id]


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


def test_payment_amendment_openapi_contract():
    paths = app.openapi()["paths"]

    required = {
        (
            "GET",
            "/purchase/orders/{po_id}/payment-summary",
        ),
        (
            "POST",
            (
                "/purchase/orders/{po_id}/costs/"
                "{cost_id}/confirm-actual"
            ),
        ),
        (
            "POST",
            "/purchase/orders/{po_id}/amendments",
        ),
        (
            "POST",
            (
                "/purchase/orders/{po_id}/amendments/"
                "{amendment_id}/submit"
            ),
        ),
        (
            "PATCH",
            (
                "/purchase/orders/{po_id}/amendments/"
                "{amendment_id}/approval"
            ),
        ),
        (
            "POST",
            "/financial_management/receipts",
        ),
        (
            "GET",
            (
                "/financial_management/receipts/"
                "{receipt_id}/purchase-cost-allocations"
            ),
        ),
    }

    actual = {
        (
            method.upper(),
            path,
        )
        for path, definition in paths.items()
        for method in definition
        if method.lower()
        in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }
    }

    assert required.issubset(actual)

    assert (
        paths[
            "/purchase/orders/{po_id}/amendments"
        ]["post"]["responses"]
        .keys()
        >= {
            "201",
            "422",
        }
    )

    assert (
        paths[
            (
                "/purchase/orders/{po_id}/costs/"
                "{cost_id}/confirm-actual"
            )
        ]["post"]["responses"]
        .keys()
        >= {
            "200",
            "422",
        }
    )

    assert (
        paths[
            "/financial_management/receipts"
        ]["post"]["responses"]
        .keys()
        >= {
            "201",
            "422",
        }
    )


@pytest.mark.skipif(
    not RUN_DATABASE_SCENARIO,
    reason=(
        "Set RUN_PHASE1_PAYMENT_AMENDMENT_E2E=1 "
        "and use a disposable migrated database"
    ),
)
def test_payment_actual_cost_and_amendment_workflow():
    db = SessionLocal()
    marker = uuid4().hex[:10]

    run_label = (
        f"E2E payment amendment {marker}"
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
            .order_by(Item.id)
            .first()
        )

        assert template_item is not None

        item = Item(
            company_id=company.id,
            item_code=(
                f"E2E-PAY-AMEND-ITEM-{marker}"
            ),
            name=(
                f"E2E Payment Amendment Item "
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
                f"E2E-PAY-AMEND-SUP-{marker}"
            ),
            name=(
                f"E2E Payment Amendment Supplier "
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

        quantity = Decimal("6")
        original_price = Decimal("120")
        amended_price = Decimal("150")
        rejected_price = Decimal("175")

        predicted_amount = (
            quantity
            * original_price
        )

        predicted_base = quantize_money(
            predicted_amount
            * exchange_rate,
            base_currency.decimal_places,
        )

        purchase_order = (
            purchase_services
            .create_purchase_order(
                db=db,
                user=current_user,
                data={
                    "title": run_label,
                    "supplier_id": supplier.id,
                    "description": run_label,
                    "expected_delivery_date": (
                        datetime.utcnow()
                        + timedelta(days=20)
                    ),
                    "lines": [
                        {
                            "item_id": item.id,
                            "ordered_quantity": (
                                quantity
                            ),
                            "unit_id": item.unit_id,
                            "line_description": (
                                run_label
                            ),
                            "unit_price": (
                                original_price
                            ),
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

        assert purchase_order.status == (
            PurchaseOrderStatus
            .DRAFT
            .value
        )

        purchase_order = (
            purchase_services.process_approval(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                action="submit",
                note=run_label,
            )
        )

        purchase_order = (
            purchase_services.process_approval(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                action="approve",
                note=run_label,
            )
        )

        assert purchase_order.status == (
            PurchaseOrderStatus
            .ORDERED
            .value
        )

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        goods_cost = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost
                .purchase_order_id
                == purchase_order.id,
                PurchaseOrderCost.cost_type
                == "goods",
            )
            .one()
        )

        assert decimal(
            goods_cost.predicted_amount
        ) == predicted_amount

        assert decimal(
            goods_cost.predicted_amount_base
        ) == predicted_base

        assert goods_cost.actual_amount is None

        summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        initial_row = payment_row(
            summary,
            goods_cost.id,
        )

        assert initial_row[
            "payment_state"
        ] == "unpaid"

        assert decimal(
            initial_row["paid_base"]
        ) == Decimal("0")

        partial_payment = Decimal("180")

        payment_receipt = (
            create_payment_receipt(
                db=db,
                current_user=current_user,
                card=card,
                supplier=supplier,
                currency=quote_currency,
                exchange_rate=exchange_rate,
                cost=goods_cost,
                amount=partial_payment,
                description=run_label,
            )
        )

        assert payment_receipt.id is not None

        allocation = (
            db.query(
                PurchaseCostPaymentAllocation
            )
            .filter(
                PurchaseCostPaymentAllocation
                .financial_receipt_id
                == payment_receipt.id,
                PurchaseCostPaymentAllocation
                .purchase_order_cost_id
                == goods_cost.id,
            )
            .one()
        )

        partial_payment_base = quantize_money(
            partial_payment
            * exchange_rate,
            base_currency.decimal_places,
        )

        assert decimal(
            allocation.allocated_amount
        ) == partial_payment

        assert decimal(
            allocation.allocated_amount_base
        ) == partial_payment_base

        summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        advance_row = payment_row(
            summary,
            goods_cost.id,
        )

        assert advance_row[
            "payment_state"
        ] == "advance_paid"

        assert decimal(
            advance_row["paid_base"]
        ) == partial_payment_base

        with pytest.raises(
            HTTPException
        ) as actual_below_paid_error:
            (
                purchase_services
                .confirm_purchase_order_cost_actual(
                    db=db,
                    user=current_user,
                    po_id=purchase_order.id,
                    cost_id=goods_cost.id,
                    amount=Decimal("179"),
                    currency_id=(
                        quote_currency.id
                    ),
                )
            )

        assert (
            actual_below_paid_error
            .value
            .status_code
            == 422
        )

        assert (
            actual_below_paid_error
            .value
            .detail["code"]
            == (
                "PURCHASE_ORDER_"
                "COST_ACTUAL_BELOW_PAID"
            )
        )

        actual_amount = Decimal("800")

        actual_cost = (
            purchase_services
            .confirm_purchase_order_cost_actual(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                cost_id=goods_cost.id,
                amount=actual_amount,
                currency_id=(
                    quote_currency.id
                ),
            )
        )

        actual_base = quantize_money(
            actual_amount
            * exchange_rate,
            base_currency.decimal_places,
        )

        assert decimal(
            actual_cost.actual_amount
        ) == actual_amount

        assert decimal(
            actual_cost.actual_amount_base
        ) == actual_base

        assert (
            actual_cost.actual_confirmed_by_user_id
            == current_user.id
        )

        assert (
            actual_cost.actual_confirmed_at
            is not None
        )

        summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        actual_row = payment_row(
            summary,
            goods_cost.id,
        )

        assert actual_row[
            "payment_state"
        ] == "partially_paid"

        assert decimal(
            actual_row[
                "settlement_target_base"
            ]
        ) == actual_base

        assert decimal(
            actual_row["outstanding_base"]
        ) == (
            actual_base
            - partial_payment_base
        )

        purchase_order = (
            purchase_services.get_po_or_404(
                db=db,
                po_id=purchase_order.id,
                user=current_user,
            )
        )

        original_line = (
            purchase_order.lines[0]
        )

        original_line_id = (
            original_line.id
        )

        amendment = (
            amendment_service
            .open_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                reason=run_label,
            )
        )

        assert amendment.status == (
            PurchaseAmendmentStatus
            .DRAFT
            .value
        )

        assert (
            amendment.before_snapshot[
                "approval"
            ]["approval_status"]
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        assert decimal(
            amendment.before_snapshot[
                "lines"
            ][0]["unit_price"]
        ) == original_price

        amended_line = (
            purchase_services
            .update_purchase_order_line(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                line_id=original_line_id,
                data={
                    "unit_price": (
                        amended_price
                    ),
                    "notes": run_label,
                },
            )
        )

        assert decimal(
            amended_line.unit_price
        ) == amended_price

        amendment = (
            amendment_service
            .submit_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                amendment_id=amendment.id,
                note=run_label,
            )
        )

        assert amendment.status == (
            PurchaseAmendmentStatus
            .PENDING
            .value
        )

        assert amendment.proposed_snapshot is not None

        assert decimal(
            amendment.proposed_snapshot[
                "lines"
            ][0]["unit_price"]
        ) == amended_price

        with pytest.raises(
            HTTPException
        ) as pending_edit_error:
            (
                purchase_services
                .update_purchase_order_line(
                    db=db,
                    user=current_user,
                    po_id=purchase_order.id,
                    line_id=original_line_id,
                    data={
                        "unit_price": (
                            rejected_price
                        )
                    },
                )
            )

        assert (
            pending_edit_error
            .value
            .status_code
            == 422
        )

        assert (
            pending_edit_error
            .value
            .detail["code"]
            == (
                "PURCHASE_ORDER_"
                "AMENDMENT_NOT_EDITABLE"
            )
        )

        amendment = (
            amendment_service
            .decide_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                amendment_id=amendment.id,
                action="approve",
                note=run_label,
            )
        )

        assert amendment.status == (
            PurchaseAmendmentStatus
            .APPROVED
            .value
        )

        purchase_order = (
            purchase_services.get_po_or_404(
                db=db,
                po_id=purchase_order.id,
                user=current_user,
            )
        )

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        assert decimal(
            purchase_order.lines[0].unit_price
        ) == amended_price

        sync_state = (
            purchase_services
            ._synchronize_purchase_order_goods_prediction(
                db=db,
                user=current_user,
                purchase_order=purchase_order,
            )
        )

        assert sync_state == (
            "payment_review_required"
        )

        db.rollback()
        db.expire_all()

        protected_cost = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost.id
                == goods_cost.id
            )
            .one()
        )

        assert decimal(
            protected_cost.predicted_amount
        ) == predicted_amount

        assert decimal(
            protected_cost.actual_amount
        ) == actual_amount

        amended_goods_amount = (
            quantity
            * amended_price
        )

        assert amended_goods_amount != (
            predicted_amount
        )

        summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        review_row = payment_row(
            summary,
            goods_cost.id,
        )

        assert review_row[
            "payment_state"
        ] == "payment_review_required"

        assert decimal(
            review_row["paid_base"]
        ) == partial_payment_base

        assert decimal(
            review_row[
                "settlement_target_base"
            ]
        ) == actual_base

        rollback_amendment = (
            amendment_service
            .open_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                reason=(
                    f"{run_label} rollback"
                ),
            )
        )

        assert rollback_amendment.status == (
            PurchaseAmendmentStatus
            .DRAFT
            .value
        )

        changed_line = (
            purchase_services
            .update_purchase_order_line(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                line_id=original_line_id,
                data={
                    "unit_price": rejected_price,
                    "notes": (
                        f"{run_label} reject"
                    ),
                },
            )
        )

        assert decimal(
            changed_line.unit_price
        ) == rejected_price

        rollback_amendment = (
            amendment_service
            .submit_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                amendment_id=(
                    rollback_amendment.id
                ),
                note=run_label,
            )
        )

        rollback_amendment = (
            amendment_service
            .decide_purchase_order_amendment(
                db=db,
                user=current_user,
                purchase_order_id=(
                    purchase_order.id
                ),
                amendment_id=(
                    rollback_amendment.id
                ),
                action="reject",
                note=(
                    "Rejected to verify "
                    "snapshot rollback"
                ),
            )
        )

        assert rollback_amendment.status == (
            PurchaseAmendmentStatus
            .REJECTED
            .value
        )

        db.expire_all()

        purchase_order = (
            purchase_services.get_po_or_404(
                db=db,
                po_id=purchase_order.id,
                user=current_user,
            )
        )

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        assert decimal(
            purchase_order.lines[0].unit_price
        ) == amended_price

        protected_cost = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost.id
                == goods_cost.id
            )
            .one()
        )

        assert decimal(
            protected_cost.predicted_amount
        ) == predicted_amount

        assert decimal(
            protected_cost.actual_amount
        ) == actual_amount

        amendments = (
            db.query(PurchaseOrderAmendment)
            .filter(
                PurchaseOrderAmendment
                .purchase_order_id
                == purchase_order.id
            )
            .order_by(
                PurchaseOrderAmendment
                .amendment_number
            )
            .all()
        )

        assert len(amendments) == 2

        assert [
            row.status
            for row in amendments
        ] == [
            PurchaseAmendmentStatus
            .APPROVED
            .value,
            PurchaseAmendmentStatus
            .REJECTED
            .value,
        ]

        assert (
            db.query(FinancialReceipt)
            .filter(
                FinancialReceipt.id
                == payment_receipt.id
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
                .purchase_order_cost_id
                == goods_cost.id
            )
            .count()
            == 1
        )

        assert (
            db.query(PurchasePhaseAllocation)
            .join(
                PurchaseOrderLine,
                PurchaseOrderLine.id
                == PurchasePhaseAllocation
                .purchase_order_line_id,
            )
            .filter(
                PurchaseOrderLine
                .purchase_order_id
                == purchase_order.id
            )
            .count()
            == 1
        )

        print()
        print(
            "PAYMENT / AMENDMENT REFERENCES"
        )
        print(
            "PO:",
            purchase_order.reference_number,
        )
        print(
            "GOODS COST:",
            goods_cost.id,
        )
        print(
            "PAYMENT RECEIPT:",
            payment_receipt.id,
        )
        print(
            "PAYMENT ALLOCATION:",
            allocation.id,
        )
        print(
            "PARTIAL PAYMENT:",
            partial_payment,
            quote_currency.code,
        )
        print(
            "ACTUAL COST:",
            actual_amount,
            quote_currency.code,
        )
        print(
            "ORIGINAL PRICE:",
            original_price,
        )
        print(
            "APPROVED AMENDED PRICE:",
            amended_price,
        )
        print(
            "REJECTED PRICE:",
            rejected_price,
        )
        print(
            "FINAL PRICE:",
            purchase_order.lines[0].unit_price,
        )
        print(
            "PAYMENT STATE:",
            review_row["payment_state"],
        )
        print(
            "PAYMENT → AMENDMENT SCENARIO: PASSED"
        )

    finally:
        db.close()
