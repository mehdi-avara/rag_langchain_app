from __future__ import annotations

import os
import re
from datetime import (
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func

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
import purchase_management.direct_mr_service as direct_mr_service
from purchase_management import (
    services as purchase_services,
)
from purchase_management.models import (
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderCost,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
    PurchasePhaseStatus,
)
from purchase_management.schemas import (
    PurchaseOrderFromMRCreate,
)
from requisition_management import (
    services as requisition_services,
)
from requisition_management.models import (
    MaterialRequisition,
    MaterialRequisitionPriority,
    MaterialRequisitionStatus,
    MaterialRequisitionStatusHistory,
)
from requisition_management.schemas import (
    MaterialRequisitionCreate,
)
from rfq_management.models import (
    RequestForQuotation,
)
from shared.currency.services import (
    quantize_money,
)


RUN_DATABASE_SCENARIO = (
    os.getenv(
        "RUN_PHASE1_DIRECT_MR_E2E"
    )
    == "1"
)


def decimal(value) -> Decimal:
    return Decimal(str(value))


def test_direct_mr_route_contract_in_full_app():
    operation = app.openapi()["paths"][
        "/purchase/orders/from-mr/{mr_id}"
    ]["post"]

    assert operation["operationId"] == (
        "create_order_from_mr_"
        "purchase_orders_from_mr__mr_id__post"
    )

    request_schema = (
        operation["requestBody"]
        ["content"]
        ["application/json"]
        ["schema"]
    )

    assert request_schema == {
        "$ref": (
            "#/components/schemas/"
            "PurchaseOrderFromMRCreate"
        )
    }

    assert {
        "201",
        "422",
    }.issubset(
        operation["responses"]
    )


@pytest.mark.skipif(
    not RUN_DATABASE_SCENARIO,
    reason=(
        "Set RUN_PHASE1_DIRECT_MR_E2E=1 "
        "and use a disposable migrated database"
    ),
)
def test_multi_item_direct_mr_to_approved_po():
    db = SessionLocal()

    marker = uuid4().hex[:10]

    run_label = (
        f"E2E direct MR purchase {marker}"
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
            .order_by(FinancialCard.id)
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

        item_a = Item(
            company_id=company.id,
            item_code=(
                f"E2E-DMR-ITEM-A-{marker}"
            ),
            name=(
                f"E2E Direct MR Item A "
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

        item_b = Item(
            company_id=company.id,
            item_code=(
                f"E2E-DMR-ITEM-B-{marker}"
            ),
            name=(
                f"E2E Direct MR Item B "
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
            is_critical=True,
            created_by_user_id=(
                current_user.id
            ),
        )

        supplier = Supplier(
            company_id=company.id,
            code=(
                f"E2E-DMR-SUP-{marker}"
            ),
            name=(
                f"E2E Direct MR Supplier "
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
                item_a,
                item_b,
                supplier,
            ]
        )

        db.commit()

        for row in (
            item_a,
            item_b,
            supplier,
        ):
            db.refresh(row)

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

        quantity_a = Decimal("9")
        quantity_b = Decimal("4")

        estimated_price_a = Decimal("80")
        estimated_price_b = Decimal("150")

        estimated_base_a = quantize_money(
            estimated_price_a
            * exchange_rate,
            base_currency.decimal_places,
        )

        estimated_base_b = quantize_money(
            estimated_price_b
            * exchange_rate,
            base_currency.decimal_places,
        )

        requisition = (
            requisition_services
            .create_requisition(
                db=db,
                current_user=current_user,
                data=(
                    MaterialRequisitionCreate(
                        needed_by_date=(
                            today
                            + timedelta(days=30)
                        ),
                        reason=run_label,
                        priority=(
                            MaterialRequisitionPriority
                            .URGENT
                        ),
                        notes=run_label,
                        items=[
                            {
                                "item_id": item_a.id,
                                "quantity": quantity_a,
                                "estimated_unit_cost": (
                                    estimated_price_a
                                ),
                                "currency_id": (
                                    quote_currency.id
                                ),
                                "estimated_unit_cost_base": (
                                    estimated_base_a
                                ),
                                "base_currency_id": (
                                    base_currency.id
                                ),
                                "exchange_rate_used": (
                                    exchange_rate
                                ),
                                "notes": run_label,
                            },
                            {
                                "item_id": item_b.id,
                                "quantity": quantity_b,
                                "estimated_unit_cost": (
                                    estimated_price_b
                                ),
                                "currency_id": (
                                    quote_currency.id
                                ),
                                "estimated_unit_cost_base": (
                                    estimated_base_b
                                ),
                                "base_currency_id": (
                                    base_currency.id
                                ),
                                "exchange_rate_used": (
                                    exchange_rate
                                ),
                                "notes": run_label,
                            },
                        ],
                    )
                    .model_dump(mode="python")
                ),
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .DRAFT
            .value
        )

        assert len(requisition.items) == 2

        requisition_items = {
            row.item_id: row
            for row in requisition.items
        }

        assert set(requisition_items) == {
            item_a.id,
            item_b.id,
        }

        direct_price_a = Decimal("75")
        direct_price_b = Decimal("140")

        expected_delivery = (
            datetime.utcnow()
            + timedelta(days=20)
        )

        full_payload = (
            PurchaseOrderFromMRCreate(
                supplier_id=supplier.id,
                title=run_label,
                description=(
                    "Direct purchase from "
                    "approved material requisition"
                ),
                expected_delivery_date=(
                    expected_delivery
                ),
                lines=[
                    {
                        "requisition_item_id": (
                            requisition_items[
                                item_a.id
                            ].id
                        ),
                        "line_description": (
                            "Direct line A"
                        ),
                        "unit_price": (
                            direct_price_a
                        ),
                        "currency_id": (
                            quote_currency.id
                        ),
                        "exchange_rate_used": (
                            exchange_rate
                        ),
                        "notes": run_label,
                    },
                    {
                        "requisition_item_id": (
                            requisition_items[
                                item_b.id
                            ].id
                        ),
                        "line_description": (
                            "Direct line B"
                        ),
                        "unit_price": (
                            direct_price_b
                        ),
                        "currency_id": (
                            quote_currency.id
                        ),
                        "exchange_rate_used": (
                            exchange_rate
                        ),
                        "notes": run_label,
                    },
                ],
            )
            .model_dump(mode="python")
        )

        with pytest.raises(
            HTTPException
        ) as draft_conversion_error:
            direct_mr_service.create_purchase_order_from_mr(
                db=db,
                user=current_user,
                requisition_id=requisition.id,
                data=full_payload,
            )

        assert (
            draft_conversion_error
            .value
            .status_code
            == 422
        )

        assert (
            draft_conversion_error
            .value
            .detail["code"]
            == "PURCHASE_ORDER_MR_NOT_APPROVED"
        )

        assert (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder
                .source_material_requisition_id
                == requisition.id
            )
            .count()
            == 0
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="submit",
                note=run_label,
            )
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="start_review",
                note=run_label,
            )
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="approve",
                note=run_label,
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .APPROVED
            .value
        )

        incomplete_payload = (
            PurchaseOrderFromMRCreate(
                supplier_id=supplier.id,
                title=run_label,
                expected_delivery_date=(
                    expected_delivery
                ),
                lines=[
                    full_payload["lines"][0]
                ],
            )
            .model_dump(mode="python")
        )

        with pytest.raises(
            HTTPException
        ) as incomplete_error:
            direct_mr_service.create_purchase_order_from_mr(
                db=db,
                user=current_user,
                requisition_id=requisition.id,
                data=incomplete_payload,
            )

        assert (
            incomplete_error
            .value
            .status_code
            == 422
        )

        assert (
            incomplete_error
            .value
            .detail["code"]
            == "PURCHASE_ORDER_MR_ITEMS_INCOMPLETE"
        )

        assert (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder
                .source_material_requisition_id
                == requisition.id
            )
            .count()
            == 0
        )

        purchase_order = (
            direct_mr_service
            .create_purchase_order_from_mr(
                db=db,
                user=current_user,
                requisition_id=requisition.id,
                data=full_payload,
            )
        )

        assert re.fullmatch(
            r"PO-\d{4}-\d{4}",
            purchase_order.reference_number,
        )

        assert (
            purchase_order
            .source_material_requisition_id
            == requisition.id
        )

        assert purchase_order.source_rfq_id is None

        assert purchase_order.supplier_id == (
            supplier.id
        )

        assert purchase_order.title == (
            run_label
        )

        assert purchase_order.status == (
            PurchaseOrderStatus
            .DRAFT
            .value
        )

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .DRAFT
            .value
        )

        assert len(purchase_order.lines) == 2
        assert len(purchase_order.phases) == 1

        phase = purchase_order.phases[0]

        assert phase.status == (
            PurchasePhaseStatus
            .DRAFT
            .value
        )

        assert (
            phase.expected_delivery_date.date()
            == expected_delivery.date()
        )

        po_lines = {
            line.item_id: line
            for line in purchase_order.lines
        }

        assert set(po_lines) == {
            item_a.id,
            item_b.id,
        }

        line_a = po_lines[item_a.id]
        line_b = po_lines[item_b.id]

        assert decimal(
            line_a.ordered_quantity
        ) == quantity_a

        assert decimal(
            line_b.ordered_quantity
        ) == quantity_b

        assert line_a.unit_id == (
            requisition_items[
                item_a.id
            ].unit_id
        )

        assert line_b.unit_id == (
            requisition_items[
                item_b.id
            ].unit_id
        )

        assert decimal(
            line_a.unit_price
        ) == direct_price_a

        assert decimal(
            line_b.unit_price
        ) == direct_price_b

        expected_unit_base_a = (
            quantize_money(
                direct_price_a
                * exchange_rate,
                base_currency.decimal_places,
            )
        )

        expected_unit_base_b = (
            quantize_money(
                direct_price_b
                * exchange_rate,
                base_currency.decimal_places,
            )
        )

        assert decimal(
            line_a.unit_price_base
        ) == expected_unit_base_a

        assert decimal(
            line_b.unit_price_base
        ) == expected_unit_base_b

        assert decimal(
            line_a.exchange_rate_used
        ) == exchange_rate

        assert decimal(
            line_b.exchange_rate_used
        ) == exchange_rate

        allocations = (
            db.query(
                PurchasePhaseAllocation
            )
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
            .order_by(
                PurchaseOrderLine
                .line_number
            )
            .all()
        )

        assert len(allocations) == 2

        allocation_by_line = {
            row.purchase_order_line_id: row
            for row in allocations
        }

        assert decimal(
            allocation_by_line[
                line_a.id
            ].allocated_quantity
        ) == quantity_a

        assert decimal(
            allocation_by_line[
                line_b.id
            ].allocated_quantity
        ) == quantity_b

        source_mr = (
            db.query(MaterialRequisition)
            .filter(
                MaterialRequisition.id
                == requisition.id
            )
            .one()
        )

        assert source_mr.status == (
            MaterialRequisitionStatus
            .ORDERED
            .value
        )

        ordered_history = (
            db.query(
                MaterialRequisitionStatusHistory
            )
            .filter(
                MaterialRequisitionStatusHistory
                .material_requisition_id
                == requisition.id,
                MaterialRequisitionStatusHistory
                .action
                == "purchase_order_created",
            )
            .all()
        )

        assert len(ordered_history) == 1

        assert (
            purchase_order.reference_number
            in (
                ordered_history[0].note
                or ""
            )
        )

        assert (
            db.query(RequestForQuotation)
            .filter(
                RequestForQuotation.mr_id
                == requisition.id
            )
            .count()
            == 0
        )

        with pytest.raises(
            HTTPException
        ) as duplicate_error:
            direct_mr_service.create_purchase_order_from_mr(
                db=db,
                user=current_user,
                requisition_id=requisition.id,
                data=full_payload,
            )

        assert (
            duplicate_error
            .value
            .status_code
            == 409
        )

        assert (
            duplicate_error
            .value
            .detail["code"]
            == "PURCHASE_ORDER_MR_ALREADY_LINKED"
        )

        assert (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder
                .source_material_requisition_id
                == requisition.id
            )
            .count()
            == 1
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

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .PENDING
            .value
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

        assert (
            purchase_order.approval_status
            == PurchaseApprovalStatus
            .APPROVED
            .value
        )

        assert purchase_order.status == (
            PurchaseOrderStatus
            .ORDERED
            .value
        )

        assert all(
            purchase_phase.status
            == PurchasePhaseStatus
            .ORDERED
            .value
            for purchase_phase
            in purchase_order.phases
        )

        goods_costs = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost
                .purchase_order_id
                == purchase_order.id,
                PurchaseOrderCost
                .cost_type
                == "goods",
            )
            .all()
        )

        assert len(goods_costs) == 1

        goods_cost = goods_costs[0]

        expected_goods_amount = (
            quantity_a * direct_price_a
            + quantity_b * direct_price_b
        )

        expected_goods_base = (
            quantity_a
            * expected_unit_base_a
            + quantity_b
            * expected_unit_base_b
        )

        assert decimal(
            goods_cost.predicted_amount
        ) == expected_goods_amount

        assert decimal(
            goods_cost.predicted_amount_base
        ) == expected_goods_base

        assert goods_cost.predicted_currency_id == (
            quote_currency.id
        )

        assert goods_cost.base_currency_id == (
            base_currency.id
        )

        summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        assert decimal(
            summary["predicted_total_base"]
        ) == expected_goods_base

        assert decimal(
            summary["paid_total_base"]
        ) == Decimal("0")

        assert decimal(
            summary["outstanding_total_base"]
        ) == expected_goods_base

        assert len(summary["costs"]) == 1

        assert (
            summary["costs"][0]
            ["payment_state"]
            == "unpaid"
        )

        print()
        print(
            "DIRECT MR PURCHASE REFERENCES"
        )
        print(
            "MR:",
            requisition.mr_number,
        )
        print(
            "PO:",
            purchase_order.reference_number,
        )
        print(
            "SUPPLIER:",
            supplier.code,
        )
        print(
            "MR ITEMS:",
            len(requisition.items),
        )
        print(
            "PO LINES:",
            len(purchase_order.lines),
        )
        print(
            "PHASE ALLOCATIONS:",
            len(allocations),
        )
        print(
            "GOODS PREDICTION:",
            goods_cost.predicted_amount,
            quote_currency.code,
        )
        print(
            "DIRECT MR → PO SCENARIO: PASSED"
        )

    finally:
        db.close()
