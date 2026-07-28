from __future__ import annotations

import os
import re
from datetime import (
    date,
    datetime,
    timedelta,
)
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
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
from goods_receipt_management import (
    services as grn_services,
)
from goods_receipt_management.models import (
    GoodsReceiptItem,
    GoodsReceiptNote,
    GoodsReceiptStatus,
)
from goods_receipt_management.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
)
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
from rfq_management import (
    services as rfq_services,
)
from rfq_management.models import (
    QuotationResponse,
    QuotationResponseItem,
    RequestForQuotation,
    RFQStatus,
)
from rfq_management.schemas import (
    QuotationResponseCreate,
    RequestForQuotationCreate,
)
from shared.currency.services import (
    quantize_money,
)
from warehouse_management import (
    services as warehouse_services,
)
from warehouse_management.models import (
    StockItem,
    StockMovement,
    StockMovementType,
    StockReferenceType,
)
from warehouse_management.schemas import (
    StorageLocationCreate,
    WarehouseCreate,
    ZoneCreate,
)


RUN_DATABASE_E2E = (
    os.getenv(
        "RUN_PHASE1_PROCURE_TO_STOCK_E2E"
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


def test_procure_to_stock_route_contract():
    openapi = app.openapi()
    paths = openapi["paths"]

    required = {
        ("POST", "/requisitions"),
        (
            "POST",
            (
                "/requisitions/"
                "{requisition_id}/submit"
            ),
        ),
        (
            "POST",
            (
                "/requisitions/"
                "{requisition_id}/approval"
            ),
        ),
        ("POST", "/rfqs"),
        (
            "POST",
            "/rfqs/{rfq_id}/send",
        ),
        (
            "POST",
            "/rfqs/{rfq_id}/responses",
        ),
        (
            "POST",
            (
                "/rfqs/{rfq_id}/"
                "select-winner"
            ),
        ),
        (
            "POST",
            (
                "/purchase/orders/"
                "from-rfq/{rfq_id}"
            ),
        ),
        (
            "POST",
            (
                "/purchase/orders/"
                "{po_id}/submit"
            ),
        ),
        (
            "PATCH",
            (
                "/purchase/orders/"
                "{po_id}/approval"
            ),
        ),
        (
            "GET",
            (
                "/purchase/orders/"
                "{po_id}/payment-summary"
            ),
        ),
        (
            "POST",
            "/financial_management/receipts",
        ),
        (
            "POST",
            "/goods-receipts",
        ),
        (
            "POST",
            (
                "/goods-receipts/"
                "{goods_receipt_id}/post"
            ),
        ),
        (
            "GET",
            "/warehouse/stock",
        ),
        (
            "GET",
            "/warehouse/movements",
        ),
    }

    actual = {
        (
            method.upper(),
            path,
        )
        for path, definition
        in paths.items()
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

    operation_ids = [
        operation["operationId"]
        for definition in paths.values()
        for method, operation
        in definition.items()
        if method.lower()
        in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }
        and "operationId" in operation
    ]

    assert len(operation_ids) == len(
        set(operation_ids)
    )


def test_goods_receipt_quantity_schema_contract():
    with pytest.raises(ValidationError):
        GoodsReceiptItemCreate(
            purchase_phase_allocation_id=1,
            item_id=1,
            received_quantity=Decimal("10"),
            accepted_quantity=Decimal("7"),
            rejected_quantity=Decimal("2"),
            rejection_reason="Damaged",
            storage_location_id=1,
        )

    with pytest.raises(ValidationError):
        GoodsReceiptItemCreate(
            purchase_phase_allocation_id=1,
            item_id=1,
            received_quantity=Decimal("10"),
            accepted_quantity=Decimal("8"),
            rejected_quantity=Decimal("2"),
            rejection_reason=None,
            storage_location_id=1,
        )


@pytest.mark.skipif(
    not RUN_DATABASE_E2E,
    reason=(
        "Set RUN_PHASE1_PROCURE_TO_STOCK_E2E=1 "
        "and use a disposable migrated database"
    ),
)
def test_procure_to_stock_database_workflow(
    monkeypatch,
):
    db = SessionLocal()
    marker = uuid4().hex[:10]
    run_label = (
        f"E2E procure-to-stock {marker}"
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

        item = (
            db.query(Item)
            .filter(
                Item.company_id
                == company.id,
                Item.unit_id.is_not(None),
                Item.is_active.is_(True),
            )
            .order_by(Item.id)
            .first()
        )

        assert item is not None

        supplier = (
            db.query(Supplier)
            .filter(
                Supplier.company_id
                == company.id,
                Supplier.status == "approved",
            )
            .order_by(Supplier.id)
            .first()
        )

        if supplier is None:
            supplier = (
                db.query(Supplier)
                .filter(
                    Supplier.company_id
                    == company.id
                )
                .order_by(Supplier.id)
                .first()
            )

        assert supplier is not None

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

        unit_price = Decimal("100")

        unit_price_base = quantize_money(
            unit_price * exchange_rate,
            base_currency.decimal_places,
        )

        quantity = Decimal("10")

        baseline_receipts = int(
            db.query(
                func.count(FinancialReceipt.id)
            ).scalar()
            or 0
        )

        baseline_allocations = int(
            db.query(
                func.count(
                    PurchaseCostPaymentAllocation.id
                )
            ).scalar()
            or 0
        )

        requisition_payload = (
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
                notes=(
                    "Permanent cross-module "
                    "integration test"
                ),
                items=[
                    {
                        "item_id": item.id,
                        "quantity": quantity,
                        "estimated_unit_cost": (
                            unit_price
                        ),
                        "currency_id": (
                            quote_currency.id
                        ),
                        "estimated_unit_cost_base": (
                            unit_price_base
                        ),
                        "base_currency_id": (
                            base_currency.id
                        ),
                        "exchange_rate_used": (
                            exchange_rate
                        ),
                        "notes": run_label,
                    }
                ],
            )
            .model_dump(mode="python")
        )

        requisition = (
            requisition_services
            .create_requisition(
                db=db,
                current_user=current_user,
                data=requisition_payload,
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .DRAFT
            .value
        )

        assert re.fullmatch(
            r"MR-\d{4}-\d{4}",
            requisition.mr_number,
        )

        assert len(requisition.items) == 1

        with pytest.raises(
            HTTPException
        ) as direct_approval_error:
            requisition_services.transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="approve",
                note=(
                    "Invalid direct approval"
                ),
            )

        assert (
            direct_approval_error
            .value
            .status_code
            == 422
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="submit",
                note="Submitted by E2E test",
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .SUBMITTED
            .value
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="start_review",
                note="Reviewed by E2E test",
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .UNDER_REVIEW
            .value
        )

        requisition = (
            requisition_services
            .transition_requisition(
                db=db,
                current_user=current_user,
                requisition_id=requisition.id,
                action="approve",
                note="Approved by E2E test",
            )
        )

        assert requisition.status == (
            MaterialRequisitionStatus
            .APPROVED
            .value
        )

        history_actions = {
            row.action
            for row in (
                db.query(
                    MaterialRequisitionStatusHistory
                )
                .filter(
                    MaterialRequisitionStatusHistory
                    .material_requisition_id
                    == requisition.id
                )
                .all()
            )
        }

        assert {
            "created",
            "submit",
            "start_review",
            "approve",
        }.issubset(history_actions)

        outsider = SimpleNamespace(
            id=999999999,
            company_id=999999999,
        )

        with pytest.raises(
            HTTPException
        ) as tenant_error:
            requisition_services.get_requisition_or_404(
                db=db,
                current_user=outsider,
                requisition_id=requisition.id,
            )

        assert (
            tenant_error.value.status_code
            == 404
        )

        rfq_payload = (
            RequestForQuotationCreate(
                mr_id=requisition.id,
                title=run_label,
                description=(
                    "RFQ generated from the "
                    "approved MR"
                ),
                deadline_date=(
                    today
                    + timedelta(days=14)
                ),
                supplier_ids=[
                    supplier.id
                ],
                items=[],
            )
            .model_dump(mode="python")
        )

        rfq = rfq_services.create_rfq(
            db=db,
            current_user=current_user,
            data=rfq_payload,
        )

        assert rfq.status == (
            RFQStatus.DRAFT.value
        )

        assert rfq.mr_id == requisition.id

        assert re.fullmatch(
            r"RFQ-\d{4}-\d{4}",
            rfq.rfq_number,
        )

        assert len(rfq.items) == 1
        assert len(rfq.suppliers) == 1
        assert rfq.items[0].item_id == item.id
        assert (
            decimal(rfq.items[0].quantity)
            == quantity
        )

        rfq = rfq_services.transition_rfq(
            db=db,
            current_user=current_user,
            rfq_id=rfq.id,
            action="send",
        )

        assert rfq.status == (
            RFQStatus.SENT.value
        )

        rfq_item = rfq.items[0]

        quotation_payload = (
            QuotationResponseCreate(
                supplier_id=supplier.id,
                received_at=datetime.utcnow(),
                valid_until=(
                    today
                    + timedelta(days=10)
                ),
                payment_terms="40/60",
                delivery_days=7,
                notes=run_label,
                items=[
                    {
                        "rfq_item_id": (
                            rfq_item.id
                        ),
                        "unit_price": (
                            unit_price
                        ),
                        "currency_id": (
                            quote_currency.id
                        ),
                        "unit_price_base": (
                            unit_price_base
                        ),
                        "base_currency_id": (
                            base_currency.id
                        ),
                        "exchange_rate_used": (
                            exchange_rate
                        ),
                        "lead_time_days": 7,
                        "notes": run_label,
                    }
                ],
            )
            .model_dump(mode="python")
        )

        quotation = (
            rfq_services
            .create_quotation_response(
                db=db,
                current_user=current_user,
                rfq_id=rfq.id,
                data=quotation_payload,
            )
        )

        assert quotation.supplier_id == (
            supplier.id
        )

        assert len(quotation.items) == 1

        quote_item = quotation.items[0]

        assert decimal(
            quote_item.unit_price
        ) == unit_price

        assert decimal(
            quote_item.unit_price_base
        ) == unit_price_base

        assert decimal(
            quote_item.exchange_rate_used
        ) == exchange_rate

        rfq = (
            rfq_services
            .select_winning_quotation(
                db=db,
                current_user=current_user,
                rfq_id=rfq.id,
                quotation_response_id=(
                    quotation.id
                ),
            )
        )

        assert rfq.status == (
            RFQStatus.CLOSED.value
        )

        winner = (
            rfq_services
            .get_winning_quotation_reference_for_purchase(
                db=db,
                current_user=current_user,
                rfq_id=rfq.id,
            )
        )

        assert winner["supplier_id"] == (
            supplier.id
        )

        assert winner["currency_id"] == (
            quote_currency.id
        )

        assert winner["base_currency_id"] == (
            base_currency.id
        )

        assert decimal(
            winner["exchange_rate_used"]
        ) == exchange_rate

        purchase_order = (
            purchase_services
            .create_purchase_order_from_rfq(
                db=db,
                user=current_user,
                rfq_id=rfq.id,
            )
        )

        assert purchase_order.source_rfq_id == (
            rfq.id
        )

        assert (
            purchase_order
            .source_material_requisition_id
            is None
        )

        source_rfq = (
            db.query(RequestForQuotation)
            .filter(
                RequestForQuotation.id
                == purchase_order.source_rfq_id
            )
            .one()
        )

        assert source_rfq.mr_id == (
            requisition.id
        )

        assert purchase_order.supplier_id == (
            supplier.id
        )

        assert re.fullmatch(
            r"PO-\d{4}-\d{4}",
            purchase_order.reference_number,
        )

        assert len(purchase_order.lines) == 1
        assert len(purchase_order.phases) == 1

        purchase_line = (
            purchase_order.lines[0]
        )

        phase = purchase_order.phases[0]

        assert purchase_line.item_id == (
            item.id
        )

        assert decimal(
            purchase_line.ordered_quantity
        ) == quantity

        assert decimal(
            purchase_line.unit_price
        ) == unit_price

        assert decimal(
            purchase_line.unit_price_base
        ) == unit_price_base

        assert phase.status == (
            PurchasePhaseStatus
            .DRAFT
            .value
        )

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

        with pytest.raises(
            HTTPException
        ) as duplicate_po_error:
            purchase_services.create_purchase_order_from_rfq(
                db=db,
                user=current_user,
                rfq_id=rfq.id,
            )

        assert (
            duplicate_po_error
            .value
            .status_code
            == 409
        )

        purchase_order = (
            purchase_services.process_approval(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
                action="submit",
                note=(
                    "Submit PO from integration "
                    "test"
                ),
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
                note=(
                    "Approve PO from integration "
                    "test"
                ),
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
            phase.status
            == PurchasePhaseStatus
            .ORDERED
            .value
            for phase
            in purchase_order.phases
        )

        goods_cost = (
            db.query(PurchaseOrderCost)
            .filter(
                PurchaseOrderCost
                .purchase_order_id
                == purchase_order.id,
                PurchaseOrderCost
                .cost_type
                == "goods",
            )
            .one()
        )

        expected_goods = (
            quantity * unit_price
        )

        expected_goods_base = (
            quantity * unit_price_base
        )

        assert decimal(
            goods_cost.predicted_amount
        ) == expected_goods

        assert decimal(
            goods_cost.predicted_amount_base
        ) == expected_goods_base

        commercial_summary = (
            purchase_services.get_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        assert decimal(
            commercial_summary[
                "total_in_base"
            ]
        ) == expected_goods_base

        assert decimal(
            commercial_summary[
                "additional_costs_base"
            ]
        ) == Decimal("0")

        assert decimal(
            commercial_summary[
                "grand_total_base"
            ]
        ) == expected_goods_base

        unpaid_summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        unpaid_row = payment_row(
            unpaid_summary,
            goods_cost.id,
        )

        assert (
            unpaid_row["payment_state"]
            == "unpaid"
        )

        monkeypatch.setattr(
            receipt_routes,
            "safe_embed_text",
            lambda _text: None,
        )

        with pytest.raises(
            HTTPException
        ) as overpayment_error:
            create_payment_receipt(
                db=db,
                current_user=current_user,
                card=card,
                supplier=supplier,
                currency=quote_currency,
                exchange_rate=exchange_rate,
                cost=goods_cost,
                amount=Decimal("1200"),
                description=(
                    f"{run_label} invalid "
                    "overpayment"
                ),
            )

        assert (
            overpayment_error
            .value
            .status_code
            in {409, 422}
        )

        db.rollback()

        assert int(
            db.query(
                func.count(FinancialReceipt.id)
            ).scalar()
            or 0
        ) == baseline_receipts

        assert int(
            db.query(
                func.count(
                    PurchaseCostPaymentAllocation.id
                )
            ).scalar()
            or 0
        ) == baseline_allocations

        partial_receipt = (
            create_payment_receipt(
                db=db,
                current_user=current_user,
                card=card,
                supplier=supplier,
                currency=quote_currency,
                exchange_rate=exchange_rate,
                cost=goods_cost,
                amount=Decimal("400"),
                description=(
                    f"{run_label} partial "
                    "payment"
                ),
            )
        )

        assert partial_receipt.id is not None

        advance_summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        advance_row = payment_row(
            advance_summary,
            goods_cost.id,
        )

        assert (
            advance_row["payment_state"]
            == "advance_paid"
        )

        assert decimal(
            advance_row["paid_base"]
        ) == quantize_money(
            Decimal("400")
            * exchange_rate,
            base_currency.decimal_places,
        )

        purchase_services.confirm_purchase_order_cost_actual(
            db=db,
            user=current_user,
            po_id=purchase_order.id,
            cost_id=goods_cost.id,
            amount=expected_goods,
            currency_id=quote_currency.id,
        )

        partial_summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        partial_row = payment_row(
            partial_summary,
            goods_cost.id,
        )

        assert (
            partial_row["payment_state"]
            == "partially_paid"
        )

        final_receipt = (
            create_payment_receipt(
                db=db,
                current_user=current_user,
                card=card,
                supplier=supplier,
                currency=quote_currency,
                exchange_rate=exchange_rate,
                cost=goods_cost,
                amount=Decimal("600"),
                description=(
                    f"{run_label} final "
                    "payment"
                ),
            )
        )

        assert final_receipt.id is not None

        paid_summary = (
            purchase_services
            .get_purchase_order_payment_summary(
                db=db,
                user=current_user,
                po_id=purchase_order.id,
            )
        )

        paid_row = payment_row(
            paid_summary,
            goods_cost.id,
        )

        assert (
            paid_row["payment_state"]
            == "paid"
        )

        assert decimal(
            paid_row["outstanding_base"]
        ) == Decimal("0")

        assert int(
            db.query(
                func.count(FinancialReceipt.id)
            ).scalar()
            or 0
        ) == baseline_receipts + 2

        assert int(
            db.query(
                func.count(
                    PurchaseCostPaymentAllocation.id
                )
            ).scalar()
            or 0
        ) == baseline_allocations + 2

        warehouse = (
            warehouse_services
            .create_warehouse(
                db=db,
                current_user=current_user,
                data=(
                    WarehouseCreate(
                        code=(
                            f"E2E{marker[:8]}"
                        ),
                        name=run_label,
                        location=(
                            "Integration test"
                        ),
                        manager_id=(
                            current_user.id
                        ),
                        is_active=True,
                        is_default=False,
                    )
                    .model_dump(
                        mode="python"
                    )
                ),
            )
        )

        zone = warehouse_services.create_zone(
            db=db,
            current_user=current_user,
            warehouse_id=warehouse.id,
            data=(
                ZoneCreate(
                    code="RCV",
                    name=(
                        "Receiving Zone"
                    ),
                    description=run_label,
                )
                .model_dump(mode="python")
            ),
        )

        location = (
            warehouse_services
            .create_storage_location(
                db=db,
                current_user=current_user,
                data=(
                    StorageLocationCreate(
                        zone_id=zone.id,
                        code="A01",
                        name=(
                            "Integration "
                            "Receiving"
                        ),
                        capacity_unit="PCS",
                        capacity_value=(
                            Decimal("1000")
                        ),
                        is_active=True,
                        is_receiving=True,
                    )
                    .model_dump(
                        mode="python"
                    )
                ),
            )
        )

        db.expire_all()

        purchase_order = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.id
                == purchase_order.id
            )
            .one()
        )

        phase = (
            db.query(PurchasePhase)
            .filter(
                PurchasePhase
                .purchase_order_id
                == purchase_order.id
            )
            .one()
        )

        phase_allocation = (
            db.query(
                PurchasePhaseAllocation
            )
            .filter(
                PurchasePhaseAllocation
                .phase_id
                == phase.id
            )
            .one()
        )

        grn_payload = (
            GoodsReceiptCreate(
                purchase_phase_id=phase.id,
                receipt_date=today,
                delivery_note_number=(
                    f"DN-{marker}"
                ),
                warehouse_id=warehouse.id,
                notes=run_label,
                items=[
                    {
                        "purchase_phase_allocation_id": (
                            phase_allocation.id
                        ),
                        "item_id": item.id,
                        "received_quantity": (
                            Decimal("10")
                        ),
                        "accepted_quantity": (
                            Decimal("8")
                        ),
                        "rejected_quantity": (
                            Decimal("2")
                        ),
                        "rejection_reason": (
                            "Two units damaged"
                        ),
                        "storage_location_id": (
                            location.id
                        ),
                        "notes": run_label,
                    }
                ],
            )
            .model_dump(mode="python")
        )

        goods_receipt = (
            grn_services
            .create_goods_receipt(
                db=db,
                current_user=current_user,
                data=grn_payload,
            )
        )

        assert goods_receipt.status == (
            GoodsReceiptStatus
            .DRAFT
            .value
        )

        assert re.fullmatch(
            r"GRN-\d{4}-\d{4}",
            goods_receipt.grn_number,
        )

        dispatched_ids: list[int] = []

        monkeypatch.setattr(
            grn_services,
            "dispatch_warehouse_grn_event",
            lambda goods_receipt_id: (
                dispatched_ids.append(
                    goods_receipt_id
                )
            ),
        )

        goods_receipt = (
            grn_services
            .post_goods_receipt(
                db=db,
                current_user=current_user,
                goods_receipt_id=(
                    goods_receipt.id
                ),
            )
        )

        assert goods_receipt.status == (
            GoodsReceiptStatus
            .POSTED
            .value
        )

        assert dispatched_ids == [
            goods_receipt.id
        ]

        warehouse_services.process_grn_receipt(
            db=db,
            goods_receipt_id=(
                goods_receipt.id
            ),
        )

        warehouse_services.process_grn_receipt(
            db=db,
            goods_receipt_id=(
                goods_receipt.id
            ),
        )

        stock = (
            db.query(StockItem)
            .filter(
                StockItem.company_id
                == company.id,
                StockItem.item_id
                == item.id,
                StockItem.storage_location_id
                == location.id,
            )
            .one()
        )

        assert decimal(
            stock.quantity_on_hand
        ) == Decimal("8")

        assert decimal(
            stock.quantity_available
        ) == Decimal("8")

        assert stock.unit_cost_currency_id == (
            base_currency.id
        )

        assert decimal(
            stock.unit_cost
        ) == unit_price_base

        assert decimal(
            stock.unit_cost_base
        ) == unit_price_base

        movements = (
            db.query(StockMovement)
            .filter(
                StockMovement.company_id
                == company.id,
                StockMovement.item_id
                == item.id,
                StockMovement.reference_type
                == StockReferenceType
                .GRN
                .value,
                StockMovement.reference_id
                == goods_receipt.id,
            )
            .all()
        )

        assert len(movements) == 1

        movement = movements[0]

        assert movement.movement_type == (
            StockMovementType
            .RECEIPT
            .value
        )

        assert decimal(
            movement.quantity
        ) == Decimal("8")

        assert movement.currency_id == (
            quote_currency.id
        )

        assert movement.base_currency_id == (
            base_currency.id
        )

        assert decimal(
            movement.unit_cost
        ) == unit_price

        assert decimal(
            movement.unit_cost_base
        ) == unit_price_base

        assert decimal(
            movement.exchange_rate_used
        ) == exchange_rate

        assert movement.to_location_id == (
            location.id
        )

        assert movement.from_location_id is None

        purchase_order = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.id
                == purchase_order.id
            )
            .one()
        )

        assert purchase_order.status == (
            PurchaseOrderStatus
            .PARTIALLY_RECEIVED
            .value
        )

        phase_allocation = (
            db.query(
                PurchasePhaseAllocation
            )
            .filter(
                PurchasePhaseAllocation.id
                == phase_allocation.id
            )
            .one()
        )

        posted_accepted_quantity = (
            db.query(
                func.coalesce(
                    func.sum(
                        GoodsReceiptItem
                        .accepted_quantity
                    ),
                    0,
                )
            )
            .join(
                GoodsReceiptNote,
                GoodsReceiptNote.id
                == GoodsReceiptItem
                .goods_receipt_note_id,
            )
            .filter(
                GoodsReceiptItem
                .purchase_phase_allocation_id
                == phase_allocation.id,
                GoodsReceiptNote.status
                == GoodsReceiptStatus
                .POSTED
                .value,
            )
            .scalar()
        )

        assert decimal(
            phase_allocation
            .allocated_quantity
        ) == Decimal("10")

        assert decimal(
            posted_accepted_quantity
        ) == Decimal("8")

        phase = (
            db.query(PurchasePhase)
            .filter(
                PurchasePhase.id
                == phase.id
            )
            .one()
        )

        assert phase.status == (
            PurchasePhaseStatus
            .SHIPPED
            .value
        )

        assert (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type
                == StockReferenceType
                .GRN
                .value,
                StockMovement.reference_id
                == goods_receipt.id,
            )
            .count()
            == 1
        )

        over_receipt_error = None

        try:
            over_receipt = (
                grn_services
                .create_goods_receipt(
                    db=db,
                    current_user=current_user,
                    data=(
                        GoodsReceiptCreate(
                            purchase_phase_id=(
                                phase.id
                            ),
                            receipt_date=today,
                            delivery_note_number=(
                                f"DN-OVER-"
                                f"{marker}"
                            ),
                            warehouse_id=(
                                warehouse.id
                            ),
                            notes=(
                                f"{run_label} "
                                "over receipt"
                            ),
                            items=[
                                {
                                    "purchase_phase_allocation_id": (
                                        phase_allocation.id
                                    ),
                                    "item_id": (
                                        item.id
                                    ),
                                    "received_quantity": (
                                        Decimal("3")
                                    ),
                                    "accepted_quantity": (
                                        Decimal("3")
                                    ),
                                    "rejected_quantity": (
                                        Decimal("0")
                                    ),
                                    "storage_location_id": (
                                        location.id
                                    ),
                                }
                            ],
                        )
                        .model_dump(
                            mode="python"
                        )
                    ),
                )
            )

            try:
                grn_services.post_goods_receipt(
                    db=db,
                    current_user=(
                        current_user
                    ),
                    goods_receipt_id=(
                        over_receipt.id
                    ),
                )
            except HTTPException as exc:
                over_receipt_error = exc

        except HTTPException as exc:
            over_receipt_error = exc

        assert over_receipt_error is not None

        assert (
            over_receipt_error.status_code
            == 422
        )

        db.rollback()
        db.expire_all()

        stock = (
            db.query(StockItem)
            .filter(
                StockItem.company_id
                == company.id,
                StockItem.item_id
                == item.id,
                StockItem.storage_location_id
                == location.id,
            )
            .one()
        )

        assert decimal(
            stock.quantity_on_hand
        ) == Decimal("8")

        assert (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type
                == StockReferenceType
                .GRN
                .value,
                StockMovement.reference_id
                == goods_receipt.id,
            )
            .count()
            == 1
        )

        assert dispatched_ids == [
            goods_receipt.id
        ]

        print()
        print(
            "PROCURE-TO-STOCK REFERENCES"
        )
        print(
            "MR:",
            requisition.mr_number,
        )
        print(
            "RFQ:",
            rfq.rfq_number,
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
            "PARTIAL RECEIPT:",
            partial_receipt.id,
        )
        print(
            "FINAL RECEIPT:",
            final_receipt.id,
        )
        print(
            "GRN:",
            goods_receipt.grn_number,
        )
        print(
            "WAREHOUSE:",
            warehouse.code,
        )
        print(
            "LOCATION:",
            location.code,
        )
        print(
            "STOCK QUANTITY:",
            stock.quantity_on_hand,
        )
        print(
            "PROCURE-TO-STOCK E2E: PASSED"
        )

    finally:
        db.close()
