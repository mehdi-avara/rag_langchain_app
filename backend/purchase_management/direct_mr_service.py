from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import User
from core.exceptions.error_codes import (
    PURCHASE_ORDER_MR_ALREADY_LINKED,
    PURCHASE_ORDER_MR_HAS_NO_ITEMS,
    PURCHASE_ORDER_MR_ITEMS_INCOMPLETE,
    PURCHASE_ORDER_MR_ITEM_INVALID,
    PURCHASE_ORDER_MR_NOT_APPROVED,
    PURCHASE_ORDER_REFERENCE_GENERATION_FAILED,
)

from .models import (
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
    PurchasePhaseStatus,
)
from .services import (
    _get_company_base_currency_reference,
    _next_reference_number,
    _prepare_purchase_order_lines,
    _resolve_supplier_for_purchase,
    _tenant_id,
    get_po_or_404,
    purchase_error,
)


def _get_purchase_order_for_mr(
    db: Session,
    user: User,
    requisition_id: int,
) -> Optional[PurchaseOrder]:
    return (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.company_id
            == _tenant_id(user),
            PurchaseOrder
            .source_material_requisition_id
            == requisition_id,
        )
        .first()
    )


def _get_requisition_reference_for_purchase(
    db: Session,
    user: User,
    requisition_id: int,
) -> dict:
    from requisition_management.services import (
        get_requisition_reference_for_purchase,
    )

    return get_requisition_reference_for_purchase(
        db=db,
        current_user=user,
        requisition_id=requisition_id,
        lock=True,
    )


def _mark_requisition_ordered_from_purchase_order(
    db: Session,
    user: User,
    requisition_id: int,
    purchase_order_reference: str,
) -> None:
    from requisition_management.services import (
        mark_requisition_ordered_from_purchase_order,
    )

    mark_requisition_ordered_from_purchase_order(
        db=db,
        current_user=user,
        requisition_id=requisition_id,
        purchase_order_reference=(
            purchase_order_reference
        ),
    )


def _expected_delivery_datetime(
    explicit_value,
    needed_by_date,
):
    if explicit_value is not None:
        return explicit_value

    if needed_by_date is None:
        return None

    if isinstance(needed_by_date, datetime):
        return needed_by_date

    return datetime.combine(
        needed_by_date,
        datetime.min.time(),
    )


def create_purchase_order_from_mr(
    db: Session,
    user: User,
    requisition_id: int,
    data: dict,
) -> PurchaseOrder:
    company_id = _tenant_id(user)

    existing = _get_purchase_order_for_mr(
        db=db,
        user=user,
        requisition_id=requisition_id,
    )

    if existing is not None:
        purchase_error(
            status.HTTP_409_CONFLICT,
            PURCHASE_ORDER_MR_ALREADY_LINKED,
            "A purchase order already exists "
            "for this material requisition",
        )

    source = (
        _get_requisition_reference_for_purchase(
            db=db,
            user=user,
            requisition_id=requisition_id,
        )
    )

    if source["status"] != "approved":
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_MR_NOT_APPROVED,
            "Only approved material requisitions "
            "can be converted directly to a "
            "purchase order",
        )

    source_items = list(
        source.get("items") or []
    )

    if not source_items:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_MR_HAS_NO_ITEMS,
            "Material requisition contains no items",
        )

    source_items_by_id = {
        int(item["id"]): item
        for item in source_items
    }
    selected_item_ids = {
        int(line["requisition_item_id"])
        for line in data.get("lines") or []
    }
    source_item_ids = set(
        source_items_by_id
    )

    if selected_item_ids != source_item_ids:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_MR_ITEMS_INCOMPLETE,
            "Direct purchase conversion must "
            "include every material requisition "
            "item exactly once",
        )

    prepared_input_lines = []

    for request_line in data.get("lines") or []:
        requisition_item_id = int(
            request_line[
                "requisition_item_id"
            ]
        )
        source_item = source_items_by_id.get(
            requisition_item_id
        )

        if source_item is None:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_MR_ITEM_INVALID,
                "A selected requisition item "
                "does not belong to the source MR",
            )

        if (
            source_item.get("item_id") is None
            or source_item.get("unit_id") is None
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_MR_ITEM_INVALID,
                "Selected requisition items require "
                "material and unit references",
            )

        ordered_quantity = Decimal(
            str(source_item["quantity"])
        )

        if ordered_quantity <= 0:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_MR_ITEM_INVALID,
                "Selected requisition items require "
                "a positive approved quantity",
            )

        prepared_input_lines.append(
            {
                "item_id": source_item["item_id"],
                "ordered_quantity": (
                    ordered_quantity
                ),
                "unit_id": source_item[
                    "unit_id"
                ],
                "line_description": (
                    (
                        request_line.get(
                            "line_description"
                        )
                        or source_item.get(
                            "item_name"
                        )
                        or ""
                    ).strip()
                    or None
                ),
                "unit_price": request_line[
                    "unit_price"
                ],
                "currency_id": request_line[
                    "currency_id"
                ],
                "exchange_rate_used": (
                    request_line[
                        "exchange_rate_used"
                    ]
                ),
                "notes": (
                    (
                        request_line.get("notes")
                        or source_item.get("notes")
                        or ""
                    ).strip()
                    or None
                ),
            }
        )

    supplier_id, supplier_name = (
        _resolve_supplier_for_purchase(
            db=db,
            user=user,
            supplier_id=data["supplier_id"],
        )
    )
    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=company_id,
        )
    )
    prepared_lines = (
        _prepare_purchase_order_lines(
            db=db,
            user=user,
            lines=prepared_input_lines,
            base_currency=base_currency,
        )
    )
    expected_delivery_date = (
        _expected_delivery_datetime(
            data.get(
                "expected_delivery_date"
            ),
            source.get("needed_by_date"),
        )
    )

    for _ in range(5):
        try:
            reference_number = (
                _next_reference_number(
                    db=db,
                    company_id=company_id,
                )
            )

            description_parts = [
                (
                    f"Created directly from MR "
                    f"{source['mr_number']}."
                ),
                (
                    data.get("description")
                    or ""
                ).strip(),
                (
                    f"MR reason: "
                    f"{source.get('reason')}"
                    if source.get("reason")
                    else ""
                ),
            ]
            description = " ".join(
                part
                for part in description_parts
                if part
            )

            purchase_order = PurchaseOrder(
                company_id=company_id,
                reference_number=(
                    reference_number
                ),
                title=(
                    (
                        data.get("title")
                        or ""
                    ).strip()
                    or (
                        "Direct purchase for "
                        f"{source['mr_number']}"
                    )
                ),
                source_rfq_id=None,
                source_material_requisition_id=(
                    source["id"]
                ),
                supplier_id=supplier_id,
                description=description,
                created_by_user_id=user.id,
                status=(
                    PurchaseOrderStatus
                    .DRAFT.value
                ),
                approval_status=(
                    PurchaseApprovalStatus
                    .DRAFT.value
                ),
            )
            purchase_order._supplier_display_name = (
                supplier_name
            )
            db.add(purchase_order)
            db.flush()

            phase = PurchasePhase(
                purchase_order_id=(
                    purchase_order.id
                ),
                phase_number=1,
                title=(
                    f"MR {source['mr_number']} "
                    "delivery"
                ),
                description=(
                    "Initial delivery phase for "
                    "direct MR purchase"
                ),
                status=(
                    PurchasePhaseStatus
                    .DRAFT.value
                ),
                expected_delivery_date=(
                    expected_delivery_date
                ),
            )
            db.add(phase)
            db.flush()

            for line_data in prepared_lines:
                purchase_line = (
                    PurchaseOrderLine(
                        purchase_order_id=(
                            purchase_order.id
                        ),
                        line_number=line_data[
                            "line_number"
                        ],
                        item_id=line_data[
                            "item_id"
                        ],
                        ordered_quantity=(
                            line_data[
                                "ordered_quantity"
                            ]
                        ),
                        unit_id=line_data[
                            "unit_id"
                        ],
                        line_description=(
                            line_data[
                                "line_description"
                            ]
                        ),
                        unit_price=line_data[
                            "unit_price"
                        ],
                        currency_id=line_data[
                            "currency_id"
                        ],
                        unit_price_base=(
                            line_data[
                                "unit_price_base"
                            ]
                        ),
                        exchange_rate_used=(
                            line_data[
                                "exchange_rate_used"
                            ]
                        ),
                        notes=line_data["notes"],
                    )
                )
                db.add(purchase_line)
                db.flush()

                db.add(
                    PurchasePhaseAllocation(
                        phase_id=phase.id,
                        purchase_order_line_id=(
                            purchase_line.id
                        ),
                        allocated_quantity=(
                            line_data[
                                "ordered_quantity"
                            ]
                        ),
                    )
                )

            _mark_requisition_ordered_from_purchase_order(
                db=db,
                user=user,
                requisition_id=source["id"],
                purchase_order_reference=(
                    reference_number
                ),
            )

            db.commit()

            return get_po_or_404(
                db=db,
                po_id=purchase_order.id,
                user=user,
            )

        except IntegrityError as exc:
            db.rollback()
            detail = str(exc.orig)

            if (
                "uq_purchase_orders_company_source_mr"
                in detail
            ):
                                purchase_error(
                    status.HTTP_409_CONFLICT,
                    PURCHASE_ORDER_MR_ALREADY_LINKED,
                    (
                        "A purchase order already exists for "
                        "this material requisition"
                    ),
                )

            if "uq_po_company_reference" in detail:
                continue

            raise

        except Exception:
            db.rollback()
            raise

    purchase_error(
        status.HTTP_409_CONFLICT,
        PURCHASE_ORDER_REFERENCE_GENERATION_FAILED,
        "Could not generate a unique purchase "
        "order reference",
    )
