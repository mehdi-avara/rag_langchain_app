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
from pydantic import ValidationError

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
from purchase_management import (
    services as purchase_services,
)
from purchase_management.models import (
    PurchaseOrder,
)
from requisition_management import (
    services as requisition_services,
)
from requisition_management.models import (
    MaterialRequisition,
    MaterialRequisitionPriority,
    MaterialRequisitionStatus,
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
    RFQItem,
    RFQStatus,
    RFQSupplier,
)
from rfq_management.schemas import (
    QuotationResponseCreate,
    RequestForQuotationCreate,
)
from shared.currency.services import (
    quantize_money,
)


RUN_DATABASE_SCENARIO = (
    os.getenv(
        "RUN_PHASE1_MULTI_ITEM_SUPPLIER_E2E"
    )
    == "1"
)


def decimal(value) -> Decimal:
    return Decimal(str(value))


def test_rfq_schema_rejects_duplicate_suppliers():
    with pytest.raises(ValidationError):
        RequestForQuotationCreate(
            title="Duplicate supplier test",
            deadline_date=(
                date.today()
                + timedelta(days=7)
            ),
            supplier_ids=[1, 1],
            items=[
                {
                    "item_id": 1,
                    "quantity": Decimal("1"),
                }
            ],
        )


@pytest.mark.skipif(
    not RUN_DATABASE_SCENARIO,
    reason=(
        "Set RUN_PHASE1_MULTI_ITEM_SUPPLIER_E2E=1 "
        "and use a disposable migrated database"
    ),
)
def test_multi_item_multi_supplier_rfq_to_po():
    db = SessionLocal()

    marker = uuid4().hex[:10]

    run_label = (
        f"E2E multi-item supplier {marker}"
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
                f"E2E-ITEM-A-{marker}"
            ),
            name=(
                f"E2E Integration Item A "
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
                f"E2E-ITEM-B-{marker}"
            ),
            name=(
                f"E2E Integration Item B "
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

        supplier_a = Supplier(
            company_id=company.id,
            code=(
                f"E2E-SUP-A-{marker}"
            ),
            name=(
                f"E2E Supplier A {marker}"
            ),
            supplier_type="local",
            country="Iran",
            status="approved",
            notes=run_label,
            created_by_user_id=(
                current_user.id
            ),
        )

        supplier_b = Supplier(
            company_id=company.id,
            code=(
                f"E2E-SUP-B-{marker}"
            ),
            name=(
                f"E2E Supplier B {marker}"
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
                supplier_a,
                supplier_b,
            ]
        )

        db.commit()

        for row in (
            item_a,
            item_b,
            supplier_a,
            supplier_b,
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

        quantity_a = Decimal("10")
        quantity_b = Decimal("6")

        estimated_a = Decimal("110")
        estimated_b = Decimal("210")

        estimated_a_base = quantize_money(
            estimated_a * exchange_rate,
            base_currency.decimal_places,
        )

        estimated_b_base = quantize_money(
            estimated_b * exchange_rate,
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
                                    estimated_a
                                ),
                                "currency_id": (
                                    quote_currency.id
                                ),
                                "estimated_unit_cost_base": (
                                    estimated_a_base
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
                                    estimated_b
                                ),
                                "currency_id": (
                                    quote_currency.id
                                ),
                                "estimated_unit_cost_base": (
                                    estimated_b_base
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

        assert re.fullmatch(
            r"MR-\d{4}-\d{4}",
            requisition.mr_number,
        )

        assert len(requisition.items) == 2

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

        rfq = rfq_services.create_rfq(
            db=db,
            current_user=current_user,
            data=(
                RequestForQuotationCreate(
                    mr_id=requisition.id,
                    title=run_label,
                    description=run_label,
                    deadline_date=(
                        today
                        + timedelta(days=14)
                    ),
                    supplier_ids=[
                        supplier_a.id,
                        supplier_b.id,
                    ],
                    items=[],
                )
                .model_dump(mode="python")
            ),
        )

        assert rfq.status == (
            RFQStatus.DRAFT.value
        )

        assert rfq.mr_id == requisition.id
        assert len(rfq.items) == 2
        assert len(rfq.suppliers) == 2

        rfq_items_by_material = {
            row.item_id: row
            for row in rfq.items
        }

        assert set(
            rfq_items_by_material
        ) == {
            item_a.id,
            item_b.id,
        }

        assert decimal(
            rfq_items_by_material[
                item_a.id
            ].quantity
        ) == quantity_a

        assert decimal(
            rfq_items_by_material[
                item_b.id
            ].quantity
        ) == quantity_b

        rfq = rfq_services.transition_rfq(
            db=db,
            current_user=current_user,
            rfq_id=rfq.id,
            action="send",
        )

        assert rfq.status == (
            RFQStatus.SENT.value
        )

        supplier_a_prices = {
            item_a.id: Decimal("100"),
            item_b.id: Decimal("200"),
        }

        supplier_b_prices = {
            item_a.id: Decimal("90"),
            item_b.id: Decimal("180"),
        }

        def create_quote(
            supplier,
            prices,
            delivery_days,
        ):
            items = []

            for material_id, rfq_item in (
                rfq_items_by_material.items()
            ):
                unit_price = prices[
                    material_id
                ]

                items.append(
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
                            quantize_money(
                                unit_price
                                * exchange_rate,
                                base_currency
                                .decimal_places,
                            )
                        ),
                        "base_currency_id": (
                            base_currency.id
                        ),
                        "exchange_rate_used": (
                            exchange_rate
                        ),
                        "lead_time_days": (
                            delivery_days
                        ),
                        "notes": run_label,
                    }
                )

            return (
                rfq_services
                .create_quotation_response(
                    db=db,
                    current_user=current_user,
                    rfq_id=rfq.id,
                    data=(
                        QuotationResponseCreate(
                            supplier_id=(
                                supplier.id
                            ),
                            received_at=(
                                datetime.utcnow()
                            ),
                            valid_until=(
                                today
                                + timedelta(
                                    days=10
                                )
                            ),
                            payment_terms="30/70",
                            delivery_days=(
                                delivery_days
                            ),
                            notes=run_label,
                            items=items,
                        )
                        .model_dump(
                            mode="python"
                        )
                    ),
                )
            )

        quotation_a = create_quote(
            supplier_a,
            supplier_a_prices,
            10,
        )

        quotation_b = create_quote(
            supplier_b,
            supplier_b_prices,
            7,
        )

        assert len(quotation_a.items) == 2
        assert len(quotation_b.items) == 2

        responses = (
            db.query(QuotationResponse)
            .filter(
                QuotationResponse.rfq_id
                == rfq.id
            )
            .order_by(
                QuotationResponse.id
            )
            .all()
        )

        assert len(responses) == 2

        response_item_count = (
            db.query(
                QuotationResponseItem
            )
            .join(
                QuotationResponse,
                QuotationResponse.id
                == QuotationResponseItem
                .quotation_response_id,
            )
            .filter(
                QuotationResponse.rfq_id
                == rfq.id
            )
            .count()
        )

        assert response_item_count == 4

        total_a = (
            supplier_a_prices[item_a.id]
            * quantity_a
            + supplier_a_prices[item_b.id]
            * quantity_b
        )

        total_b = (
            supplier_b_prices[item_a.id]
            * quantity_a
            + supplier_b_prices[item_b.id]
            * quantity_b
        )

        assert total_b < total_a

        rfq = (
            rfq_services
            .select_winning_quotation(
                db=db,
                current_user=current_user,
                rfq_id=rfq.id,
                quotation_response_id=(
                    quotation_b.id
                ),
            )
        )

        assert rfq.status == (
            RFQStatus.CLOSED.value
        )

        winner_rows = (
            db.query(QuotationResponse)
            .filter(
                QuotationResponse.rfq_id
                == rfq.id,
                QuotationResponse.is_winner
                .is_(True),
            )
            .all()
        )

        assert len(winner_rows) == 1
        assert winner_rows[0].id == (
            quotation_b.id
        )

        winner_reference = (
            rfq_services
            .get_winning_quotation_reference_for_purchase(
                db=db,
                current_user=current_user,
                rfq_id=rfq.id,
            )
        )

        assert winner_reference[
            "supplier_id"
        ] == supplier_b.id

        assert winner_reference[
            "currency_id"
        ] == quote_currency.id

        assert decimal(
            winner_reference[
                "exchange_rate_used"
            ]
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

        assert purchase_order.supplier_id == (
            supplier_b.id
        )

        assert len(purchase_order.lines) == 2

        po_lines_by_item = {
            line.item_id: line
            for line in purchase_order.lines
        }

        assert set(po_lines_by_item) == {
            item_a.id,
            item_b.id,
        }

        assert decimal(
            po_lines_by_item[
                item_a.id
            ].ordered_quantity
        ) == quantity_a

        assert decimal(
            po_lines_by_item[
                item_b.id
            ].ordered_quantity
        ) == quantity_b

        assert decimal(
            po_lines_by_item[
                item_a.id
            ].unit_price
        ) == supplier_b_prices[
            item_a.id
        ]

        assert decimal(
            po_lines_by_item[
                item_b.id
            ].unit_price
        ) == supplier_b_prices[
            item_b.id
        ]

        expected_total_base = (
            quantize_money(
                supplier_b_prices[item_a.id]
                * exchange_rate,
                base_currency.decimal_places,
            )
            * quantity_a
            + quantize_money(
                supplier_b_prices[item_b.id]
                * exchange_rate,
                base_currency.decimal_places,
            )
            * quantity_b
        )

        actual_total_base = sum(
            (
                decimal(
                    line.unit_price_base
                )
                * decimal(
                    line.ordered_quantity
                )
                for line
                in purchase_order.lines
            ),
            Decimal("0"),
        )

        assert actual_total_base == (
            expected_total_base
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
        ) as duplicate_conversion:
            purchase_services.create_purchase_order_from_rfq(
                db=db,
                user=current_user,
                rfq_id=rfq.id,
            )

        assert (
            duplicate_conversion
            .value
            .status_code
            == 409
        )

        assert (
            db.query(RFQSupplier)
            .filter(
                RFQSupplier.rfq_id
                == rfq.id
            )
            .count()
            == 2
        )

        assert (
            db.query(RFQItem)
            .filter(
                RFQItem.rfq_id
                == rfq.id
            )
            .count()
            == 2
        )

        assert (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.source_rfq_id
                == rfq.id
            )
            .count()
            == 1
        )

        print()
        print(
            "MULTI-ITEM / MULTI-SUPPLIER "
            "REFERENCES"
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
            "SUPPLIER A:",
            supplier_a.code,
        )
        print(
            "SUPPLIER B:",
            supplier_b.code,
        )
        print(
            "WINNER:",
            supplier_b.code,
        )
        print(
            "PO:",
            purchase_order.reference_number,
        )
        print(
            "MR ITEMS:",
            len(requisition.items),
        )
        print(
            "RFQ SUPPLIERS:",
            2,
        )
        print(
            "QUOTATION ITEMS:",
            response_item_count,
        )
        print(
            "PO LINES:",
            len(purchase_order.lines),
        )
        print(
            "MULTI-ITEM MULTI-SUPPLIER "
            "SCENARIO: PASSED"
        )

    finally:
        db.close()
