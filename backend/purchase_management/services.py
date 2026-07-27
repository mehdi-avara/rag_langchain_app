"""Business logic for purchase_management."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from core.exceptions.error_codes import (
    PURCHASE_ORDER_BASE_CURRENCY_NOT_CONFIGURED,
    PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
    PURCHASE_ORDER_APPROVAL_ACTION_INVALID,
    PURCHASE_ORDER_APPROVAL_INVALID_TRANSITION,
    PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
    PURCHASE_ORDER_COMMERCIAL_TERMS_MISMATCH,
    PURCHASE_PHASE_SPLIT_ALLOCATION_BLOCKED,
    PURCHASE_PHASE_SPLIT_IDEMPOTENCY_CONFLICT,
    PURCHASE_PHASE_SPLIT_IDEMPOTENCY_REQUIRED,
    PURCHASE_PHASE_SPLIT_INVALID_MOVE,
    PURCHASE_PHASE_SPLIT_NOT_ALLOWED,
    PURCHASE_PHASE_SPLIT_QUANTITY_EXCEEDS_MOVABLE,
    PURCHASE_ORDER_CURRENCY_INVALID,
    PURCHASE_ORDER_INVALID_STRUCTURE,
    PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
    PURCHASE_ORDER_LINE_NOT_FOUND,
    PURCHASE_ORDER_NOT_FOUND,
    PURCHASE_ORDER_COST_NOT_FOUND,
    PURCHASE_ORDER_COST_HAS_PAYMENTS,
    PURCHASE_ORDER_COST_ACTUAL_BELOW_PAID,
    PURCHASE_ORDER_COST_NOT_FINANCIALLY_EDITABLE,
    PURCHASE_ORDER_COST_MONEY_INCOMPLETE,
    PURCHASE_ORDER_COST_TYPE_INVALID,
    PURCHASE_ORDER_LINES_REQUIRED,
    PURCHASE_ORDER_NOT_RECEIVABLE,
    PURCHASE_ORDER_REFERENCE_GENERATION_FAILED,
    PURCHASE_ORDER_RFQ_ALREADY_LINKED,
    PURCHASE_ORDER_RFQ_INVALID_WINNER,
    PURCHASE_ORDER_SUPPLIER_REQUIRED,
    PURCHASE_PHASE_ALLOCATION_NOT_FOUND,
    PURCHASE_PHASE_ALLOCATION_OVER_RECEIPT,
    PURCHASE_PHASE_ITEM_NOT_FOUND,
    PURCHASE_PHASE_ITEM_OVER_RECEIPT,
    PURCHASE_PHASE_NOT_FOUND,
    PURCHASE_PHASE_NOT_RECEIVABLE,
    USER_HAS_NO_COMPANY,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models import User
from shared.currency.services import (
    get_currency_or_404,
    get_rate,
    quantize_exchange_rate,
    quantize_money,
)

from .models import (
    CostAllocationMethod,
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderCost,
    PurchaseOrderLine,
    PurchaseOrderReceiptLink,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
    PurchasePhaseSplitEvent,
    PurchasePhaseStatus,
)


# ── Reference number ──────────────────────────────────────────────────────────

def _next_reference_number(db: Session, company_id: int) -> str:
    year = datetime.utcnow().year
    count = (
        db.query(func.count(PurchaseOrder.id))
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.reference_number.like(f"PO-{year}-%"),
        )
        .scalar()
        or 0
    )
    return f"PO-{year}-{(count + 1):04d}"


# ── Tenant helper ─────────────────────────────────────────────────────────────

def _tenant_id(user: User) -> int:
    if user.company_id is None:
                purchase_error(
            status.HTTP_403_FORBIDDEN,
            USER_HAS_NO_COMPANY,
            "Current user does not belong to a company",
        )

    return user.company_id


def _get_purchase_order_for_rfq(
    db: Session,
    user: User,
    rfq_id: int,
) -> Optional[PurchaseOrder]:
    return (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.company_id == _tenant_id(user),
            PurchaseOrder.source_rfq_id == rfq_id,
        )
        .first()
    )


def _get_winning_quotation_reference_for_purchase(
    db: Session,
    user: User,
    rfq_id: int,
) -> dict:
    from rfq_management.services import get_winning_quotation_reference_for_purchase

    return get_winning_quotation_reference_for_purchase(
        db=db,
        current_user=user,
        rfq_id=rfq_id,
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
        purchase_order_reference=purchase_order_reference,
    )


# ── PurchaseOrder CRUD ────────────────────────────────────────────────────────

def _purchase_order_query(db: Session):
    return db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.supplier),
        selectinload(PurchaseOrder.lines).selectinload(
            PurchaseOrderLine.allocations
        ),
        selectinload(PurchaseOrder.phases).selectinload(
            PurchasePhase.allocations
        ),
        selectinload(PurchaseOrder.costs),
        selectinload(PurchaseOrder.amendments),
    )


def get_po_or_404(
    db: Session,
    po_id: int,
    user: User,
) -> PurchaseOrder:
    purchase_order = (
        _purchase_order_query(db)
        .filter(
            PurchaseOrder.id == po_id,
            PurchaseOrder.company_id == _tenant_id(user),
        )
        .first()
    )

    if purchase_order is None:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_NOT_FOUND,
            "Purchase order not found",
        )

    return purchase_order


def list_purchase_orders(
    db: Session,
    user: User,
    po_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> List[PurchaseOrder]:
    query = _purchase_order_query(db).filter(
        PurchaseOrder.company_id == _tenant_id(user)
    )

    if po_status:
        query = query.filter(
            PurchaseOrder.status == po_status
        )

    if approval_status:
        query = query.filter(
            PurchaseOrder.approval_status == approval_status
        )

    return (
        query.order_by(
            PurchaseOrder.created_at.desc(),
            PurchaseOrder.id.desc(),
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


def _resolve_supplier_for_purchase(
    db: Session,
    user: User,
    supplier_id: int,
) -> tuple[int, str]:
    from supplier_management.services import (
        get_supplier_or_404,
    )

    supplier = get_supplier_or_404(
        db=db,
        supplier_id=supplier_id,
        current_user=user,
    )

    return supplier.id, supplier.name

def _get_company_base_currency_reference(
    db: Session,
    company_id: int,
):
    from Models.company import Company
    from shared.currency.services import (
        get_currency_by_code,
        get_currency_or_404,
    )

    company = (
        db.query(Company)
        .filter(Company.id == company_id)
        .first()
    )

    if company is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_BASE_CURRENCY_NOT_CONFIGURED,
            "Company was not found",
        )

    if company.base_currency_id is not None:
        currency = get_currency_or_404(
            db=db,
            currency_id=company.base_currency_id,
        )
    else:
        currency = get_currency_by_code(
            db=db,
            code=company.base_currency,
        )

    if currency is None or not currency.is_active:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_BASE_CURRENCY_NOT_CONFIGURED,
            "Company base currency is not configured",
        )

    return currency


def _prepare_purchase_order_lines(
    db: Session,
    user: User,
    lines: list[dict],
    base_currency,
) -> list[dict]:
    from material_management.services import (
        get_item_reference,
        get_unit_or_404,
    )
    from shared.currency.services import get_currency_or_404

    if not lines:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_LINES_REQUIRED,
            "A purchase order must contain at least one line",
        )

    prepared_lines = []
    expected_currency_id = None
    expected_exchange_rate = None

    for line_number, line in enumerate(lines, start=1):
        item = get_item_reference(
            db=db,
            current_user=user,
            item_id=line["item_id"],
        )
        unit = get_unit_or_404(
            db=db,
            current_user=user,
            unit_id=line["unit_id"],
        )

        if unit.id != item["unit_id"]:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_INVALID_STRUCTURE,
                "Purchase-order line unit does not match the material unit",
            )

        currency = get_currency_or_404(
            db=db,
            currency_id=line["currency_id"],
        )

        if not currency.is_active:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_CURRENCY_INVALID,
                "Purchase-order line currency is inactive",
            )

        ordered_quantity = Decimal(
            str(line["ordered_quantity"])
        )
        exchange_rate = quantize_exchange_rate(
            line["exchange_rate_used"]
        )
        unit_price = quantize_money(
            line["unit_price"],
            currency.decimal_places,
        )
        unit_price_base = quantize_money(
            unit_price * exchange_rate,
            base_currency.decimal_places,
        )

        if expected_currency_id is None:
            expected_currency_id = currency.id
            expected_exchange_rate = exchange_rate
        elif (
            expected_currency_id != currency.id
            or expected_exchange_rate != exchange_rate
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COMMERCIAL_TERMS_MISMATCH,
                "All purchase-order lines must use the same currency and exchange rate",
            )

        prepared_lines.append(
            {
                "line_number": line_number,
                "item_id": item["id"],
                "ordered_quantity": ordered_quantity,
                "unit_id": unit.id,
                "line_description": (
                    (line.get("line_description") or "").strip()
                    or None
                ),
                "unit_price": unit_price,
                "currency_id": currency.id,
                "unit_price_base": unit_price_base,
                "exchange_rate_used": exchange_rate,
                "notes": (
                    (line.get("notes") or "").strip()
                    or None
                ),
            }
        )

    return prepared_lines


def create_purchase_order(
    db: Session,
    user: User,
    data: dict,
) -> PurchaseOrder:
    company_id = _tenant_id(user)
    supplier_id = data.get("supplier_id")

    if supplier_id is None:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_SUPPLIER_REQUIRED,
            "supplier_id is required",
        )

    resolved_supplier_id, resolved_supplier_name = (
        _resolve_supplier_for_purchase(
            db=db,
            user=user,
            supplier_id=supplier_id,
        )
    )

    base_currency = _get_company_base_currency_reference(
        db=db,
        company_id=company_id,
    )
    prepared_lines = _prepare_purchase_order_lines(
        db=db,
        user=user,
        lines=data.get("lines") or [],
        base_currency=base_currency,
    )
    for _ in range(5):
        try:
            reference_number = _next_reference_number(
                db=db,
                company_id=company_id,
            )

            purchase_order = PurchaseOrder(
                company_id=company_id,
                reference_number=reference_number,
                title=(
                    (data.get("title") or "").strip()
                    or None
                ),
                source_rfq_id=None,
                source_material_requisition_id=None,
                supplier_id=resolved_supplier_id,
                description=(
                    (data.get("description") or "").strip()
                    or None
                ),
                created_by_user_id=user.id,
                status=PurchaseOrderStatus.DRAFT.value,
                approval_status=PurchaseApprovalStatus.DRAFT.value,
            )
            purchase_order._supplier_display_name = (
                resolved_supplier_name
            )
            db.add(purchase_order)
            db.flush()

            phase = PurchasePhase(
                purchase_order_id=purchase_order.id,
                phase_number=1,
                title="Phase 1",
                description="Initial delivery phase",
                status=PurchasePhaseStatus.DRAFT.value,
                expected_delivery_date=data.get(
                    "expected_delivery_date"
                ),
            )
            db.add(phase)
            db.flush()

            for line_data in prepared_lines:
                order_line = PurchaseOrderLine(
                    purchase_order_id=purchase_order.id,
                    line_number=line_data["line_number"],
                    item_id=line_data["item_id"],
                    ordered_quantity=line_data[
                        "ordered_quantity"
                    ],
                    unit_id=line_data["unit_id"],
                    line_description=line_data[
                        "line_description"
                    ],
                    unit_price=line_data["unit_price"],
                    currency_id=line_data["currency_id"],
                    unit_price_base=line_data[
                        "unit_price_base"
                    ],
                    exchange_rate_used=line_data[
                        "exchange_rate_used"
                    ],
                    notes=line_data["notes"],
                )
                db.add(order_line)
                db.flush()

                db.add(
                    PurchasePhaseAllocation(
                        phase_id=phase.id,
                        purchase_order_line_id=order_line.id,
                        allocated_quantity=line_data[
                            "ordered_quantity"
                        ],
                    )
                )

            db.commit()

            return get_po_or_404(
                db=db,
                po_id=purchase_order.id,
                user=user,
            )

        except IntegrityError as exc:
            db.rollback()

            if "uq_po_company_reference" in str(exc.orig):
                continue

            raise

        except Exception:
            db.rollback()
            raise

    purchase_error(
        status.HTTP_409_CONFLICT,
        PURCHASE_ORDER_REFERENCE_GENERATION_FAILED,
        "Could not generate a unique purchase order reference",
    )


def create_purchase_order_from_rfq(
    db: Session,
    user: User,
    rfq_id: int,
) -> PurchaseOrder:
    existing = _get_purchase_order_for_rfq(
        db=db,
        user=user,
        rfq_id=rfq_id,
    )

    if existing is not None:
        purchase_error(
            status.HTTP_409_CONFLICT,
            PURCHASE_ORDER_RFQ_ALREADY_LINKED,
            "A purchase order already exists for this RFQ",
        )

    source = _get_winning_quotation_reference_for_purchase(
        db=db,
        user=user,
        rfq_id=rfq_id,
    )
    source_items = list(source.get("items") or [])

    if not source_items:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_RFQ_INVALID_WINNER,
            "Winning quotation contains no purchase items",
        )

    header_currency_id = source["currency_id"]
    header_base_currency_id = source["base_currency_id"]
    header_exchange_rate = Decimal(
        str(source["exchange_rate_used"])
    )

    prepared_lines: list[dict] = []

    for line_number, source_item in enumerate(
        source_items,
        start=1,
    ):
        item_id = source_item.get("item_id")
        unit_id = source_item.get("unit_id")

        if item_id is None or unit_id is None:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_RFQ_INVALID_WINNER,
                "Winning quotation contains an item without a material or unit reference",
            )

        quantity = Decimal(
            str(source_item["quantity"])
        )
        unit_price = Decimal(
            str(source_item["unit_price"])
        )
        unit_price_base = Decimal(
            str(source_item["unit_price_base"])
        )
        exchange_rate = Decimal(
            str(source_item["exchange_rate_used"])
        )

        if quantity <= 0:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_RFQ_INVALID_WINNER,
                "Winning quotation contains a non-positive quantity",
            )

        if unit_price < 0 or unit_price_base < 0:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_RFQ_INVALID_WINNER,
                "Winning quotation contains a negative price",
            )

        if exchange_rate <= 0:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_RFQ_INVALID_WINNER,
                "Winning quotation contains an invalid exchange rate",
            )

        if (
            source_item["currency_id"]
            != header_currency_id
            or source_item["base_currency_id"]
            != header_base_currency_id
            or exchange_rate != header_exchange_rate
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_RFQ_INVALID_WINNER,
                "Winning quotation item terms do not match the purchase-order header",
            )

        prepared_lines.append(
            {
                "line_number": line_number,
                "item_id": item_id,
                "ordered_quantity": quantity,
                "unit_id": unit_id,
                "line_description": (
                    (
                        source_item.get(
                            "specifications"
                        )
                        or source_item.get("item_name")
                        or ""
                    ).strip()
                    or None
                ),
                "unit_price": unit_price,
                "currency_id": source_item[
                    "currency_id"
                ],
                "unit_price_base": unit_price_base,
                "exchange_rate_used": exchange_rate,
                "notes": (
                    (
                        source_item.get("notes")
                        or ""
                    ).strip()
                    or None
                ),
            }
        )

    for _ in range(5):
        try:
            reference_number = _next_reference_number(
                db=db,
                company_id=_tenant_id(user),
            )

            description_parts = [
                (
                    f"Created from RFQ "
                    f"{source['rfq_number']}."
                ),
                (
                    source.get("description")
                    or ""
                ).strip(),
            ]
            description = " ".join(
                part
                for part in description_parts
                if part
            )

            purchase_order = PurchaseOrder(
                company_id=_tenant_id(user),
                reference_number=reference_number,
                title=source["title"],
                source_rfq_id=source["rfq_id"],
                source_material_requisition_id=None,
                supplier_id=source["supplier_id"],
                description=description,
                created_by_user_id=user.id,
                status=PurchaseOrderStatus.DRAFT.value,
                approval_status=(
                    PurchaseApprovalStatus.DRAFT.value
                ),
            )
            purchase_order._supplier_display_name = (
                source.get("supplier_name")
            )
            db.add(purchase_order)
            db.flush()

            delivery_days = source.get(
                "delivery_days"
            )
            expected_delivery_date = (
                datetime.utcnow()
                + timedelta(days=delivery_days)
                if delivery_days is not None
                else None
            )

            purchase_phase = PurchasePhase(
                purchase_order_id=purchase_order.id,
                phase_number=1,
                title=(
                    f"RFQ {source['rfq_number']} "
                    "delivery"
                ),
                description=(
                    "Generated from the selected "
                    "quotation response"
                ),
                status=PurchasePhaseStatus.DRAFT.value,
                expected_delivery_date=(
                    expected_delivery_date
                ),
            )
            db.add(purchase_phase)
            db.flush()

            for line_data in prepared_lines:
                purchase_line = PurchaseOrderLine(
                    purchase_order_id=(
                        purchase_order.id
                    ),
                    line_number=line_data[
                        "line_number"
                    ],
                    item_id=line_data["item_id"],
                    ordered_quantity=line_data[
                        "ordered_quantity"
                    ],
                    unit_id=line_data["unit_id"],
                    line_description=line_data[
                        "line_description"
                    ],
                    unit_price=line_data[
                        "unit_price"
                    ],
                    currency_id=line_data[
                        "currency_id"
                    ],
                    unit_price_base=line_data[
                        "unit_price_base"
                    ],
                    exchange_rate_used=line_data[
                        "exchange_rate_used"
                    ],
                    notes=line_data["notes"],
                )
                db.add(purchase_line)
                db.flush()

                db.add(
                    PurchasePhaseAllocation(
                        phase_id=purchase_phase.id,
                        purchase_order_line_id=(
                            purchase_line.id
                        ),
                        allocated_quantity=line_data[
                            "ordered_quantity"
                        ],
                    )
                )

            if source.get("mr_id") is not None:
                _mark_requisition_ordered_from_purchase_order(
                    db=db,
                    user=user,
                    requisition_id=source["mr_id"],
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
                "uq_purchase_orders_company_rfq"
                in detail
            ):
                                purchase_error(
                    status.HTTP_409_CONFLICT,
                    PURCHASE_ORDER_RFQ_ALREADY_LINKED,
                    "A purchase order already exists for this RFQ",
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
        "Could not generate a unique purchase order reference",
    )


def update_purchase_order(
    db: Session,
    user: User,
    po_id: int,
    **kwargs,
) -> PurchaseOrder:
    po = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    if kwargs:
        _assert_purchase_order_commercial_mutation_allowed(
            db=db,
            purchase_order=po,
        )

    missing = object()
    supplied_supplier_id = kwargs.pop(
        "supplier_id",
        missing,
    )

    if supplied_supplier_id is not missing:
        if supplied_supplier_id is None:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_SUPPLIER_REQUIRED,
                "supplier_id is required",
            )

        resolved_supplier_id, supplier_name = (
            _resolve_supplier_for_purchase(
                db=db,
                user=user,
                supplier_id=supplied_supplier_id,
            )
        )
        po.supplier_id = resolved_supplier_id
        po._supplier_display_name = supplier_name

    for key, value in kwargs.items():
        if value is not None:
            setattr(po, key, value)

    db.commit()
    db.refresh(po)

    return get_po_or_404(
        db=db,
        po_id=po.id,
        user=user,
    )


def _assert_purchase_order_commercial_mutation_allowed(
    db: Session,
    purchase_order: PurchaseOrder,
) -> None:
    from .amendment_service import (
        _purchase_order_has_posted_receipts,
        assert_purchase_order_commercially_editable,
    )

    assert_purchase_order_commercially_editable(
        db=db,
        purchase_order=purchase_order,
    )

    if _purchase_order_has_posted_receipts(
        db=db,
        purchase_order_id=purchase_order.id,
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
            (
                "Commercial terms cannot be changed "
                "after a posted goods receipt"
            ),
        )


def _get_purchase_order_line_or_404(
    db: Session,
    purchase_order_id: int,
    line_id: int,
) -> PurchaseOrderLine:
    line = (
        db.query(PurchaseOrderLine)
        .options(
            selectinload(
                PurchaseOrderLine.allocations
            )
        )
        .filter(
            PurchaseOrderLine.id == line_id,
            PurchaseOrderLine.purchase_order_id
            == purchase_order_id,
        )
        .first()
    )

    if line is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_LINE_NOT_FOUND,
            "Purchase-order line not found",
        )

    return line


def _reload_purchase_order_line(
    db: Session,
    purchase_order_id: int,
    line_id: int,
) -> PurchaseOrderLine:
    db.expire_all()

    return _get_purchase_order_line_or_404(
        db=db,
        purchase_order_id=purchase_order_id,
        line_id=line_id,
    )


def _get_purchase_order_cost_or_404(
    db: Session,
    purchase_order_id: int,
    cost_id: int,
) -> PurchaseOrderCost:
    cost = (
        db.query(PurchaseOrderCost)
        .filter(
            PurchaseOrderCost.id == cost_id,
            PurchaseOrderCost.purchase_order_id
            == purchase_order_id,
        )
        .first()
    )

    if cost is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_COST_NOT_FOUND,
            "Purchase-order cost not found",
        )

    return cost


def _validate_purchase_order_line_allocations(
    db: Session,
    purchase_order: PurchaseOrder,
    allocations: list[dict],
    ordered_quantity: Decimal,
) -> list[dict]:
    if not allocations:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
            (
                "At least one delivery allocation "
                "is required"
            ),
        )

    phase_ids = [
        int(allocation["phase_id"])
        for allocation in allocations
    ]

    if len(phase_ids) != len(set(phase_ids)):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
            (
                "Each delivery phase may appear "
                "only once"
            ),
        )

    phases = (
        db.query(PurchasePhase)
        .filter(
            PurchasePhase.purchase_order_id
            == purchase_order.id,
            PurchasePhase.id.in_(phase_ids),
        )
        .all()
    )

    if {
        phase.id
        for phase in phases
    } != set(phase_ids):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
            (
                "One or more delivery phases do not "
                "belong to the purchase order"
            ),
        )

    normalized = [
        {
            "phase_id": int(
                allocation["phase_id"]
            ),
            "allocated_quantity": Decimal(
                str(
                    allocation[
                        "allocated_quantity"
                    ]
                )
            ),
        }
        for allocation in allocations
    ]

    total = sum(
        (
            allocation["allocated_quantity"]
            for allocation in normalized
        ),
        Decimal("0"),
    )

    if total != Decimal(str(ordered_quantity)):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
            (
                "Allocation total must equal "
                "ordered quantity"
            ),
        )

    return normalized


def _prepare_mutated_purchase_order_line(
    db: Session,
    user: User,
    purchase_order: PurchaseOrder,
    data: dict,
    excluded_line_id: Optional[int] = None,
) -> dict:
    required_fields = (
        "item_id",
        "ordered_quantity",
        "unit_id",
        "unit_price",
        "currency_id",
        "exchange_rate_used",
    )

    if any(
        data.get(field) is None
        for field in required_fields
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            (
                "Purchase-order line contains "
                "missing commercial fields"
            ),
        )

    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=purchase_order.company_id,
        )
    )

    prepared = _prepare_purchase_order_lines(
        db=db,
        user=user,
        lines=[data],
        base_currency=base_currency,
    )[0]

    query = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.purchase_order_id
        == purchase_order.id
    )

    if excluded_line_id is not None:
        query = query.filter(
            PurchaseOrderLine.id
            != excluded_line_id
        )

    other_lines = query.all()

    for other_line in other_lines:
        if (
            other_line.currency_id
            != prepared["currency_id"]
            or Decimal(
                str(
                    other_line
                    .exchange_rate_used
                )
            )
            != Decimal(
                str(
                    prepared[
                        "exchange_rate_used"
                    ]
                )
            )
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COMMERCIAL_TERMS_MISMATCH,
                (
                    "All purchase-order lines must "
                    "use the same currency and "
                    "exchange rate"
                ),
            )

    return prepared


def create_purchase_order_line(
    db: Session,
    user: User,
    po_id: int,
    data: dict,
) -> PurchaseOrderLine:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    _assert_purchase_order_commercial_mutation_allowed(
        db=db,
        purchase_order=purchase_order,
    )

    values = dict(data)
    allocations = values.pop(
        "allocations",
        None,
    )

    prepared = _prepare_mutated_purchase_order_line(
        db=db,
        user=user,
        purchase_order=purchase_order,
        data=values,
    )

    normalized_allocations = (
        _validate_purchase_order_line_allocations(
            db=db,
            purchase_order=purchase_order,
            allocations=allocations,
            ordered_quantity=prepared[
                "ordered_quantity"
            ],
        )
    )

    line_number = (
        db.query(
            func.coalesce(
                func.max(
                    PurchaseOrderLine.line_number
                ),
                0,
            )
        )
        .filter(
            PurchaseOrderLine.purchase_order_id
            == purchase_order.id
        )
        .scalar()
        + 1
    )

    line = PurchaseOrderLine(
        purchase_order_id=purchase_order.id,
        line_number=line_number,
        item_id=prepared["item_id"],
        ordered_quantity=prepared[
            "ordered_quantity"
        ],
        unit_id=prepared["unit_id"],
        line_description=prepared[
            "line_description"
        ],
        unit_price=prepared["unit_price"],
        currency_id=prepared["currency_id"],
        unit_price_base=prepared[
            "unit_price_base"
        ],
        exchange_rate_used=prepared[
            "exchange_rate_used"
        ],
        notes=prepared["notes"],
    )

    db.add(line)
    db.flush()

    for allocation in normalized_allocations:
        db.add(
            PurchasePhaseAllocation(
                phase_id=allocation["phase_id"],
                purchase_order_line_id=line.id,
                allocated_quantity=allocation[
                    "allocated_quantity"
                ],
            )
        )

    line_id = line.id
    db.commit()

    return _reload_purchase_order_line(
        db=db,
        purchase_order_id=purchase_order.id,
        line_id=line_id,
    )


def update_purchase_order_line(
    db: Session,
    user: User,
    po_id: int,
    line_id: int,
    data: dict,
) -> PurchaseOrderLine:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    _assert_purchase_order_commercial_mutation_allowed(
        db=db,
        purchase_order=purchase_order,
    )

    line = _get_purchase_order_line_or_404(
        db=db,
        purchase_order_id=purchase_order.id,
        line_id=line_id,
    )

    values = dict(data)
    allocations_supplied = (
        "allocations" in values
    )
    allocations = values.pop(
        "allocations",
        None,
    )

    merged = {
        "item_id": line.item_id,
        "ordered_quantity": (
            line.ordered_quantity
        ),
        "unit_id": line.unit_id,
        "line_description": (
            line.line_description
        ),
        "unit_price": line.unit_price,
        "currency_id": line.currency_id,
        "exchange_rate_used": (
            line.exchange_rate_used
        ),
        "notes": line.notes,
    }

    merged.update(values)

    prepared = _prepare_mutated_purchase_order_line(
        db=db,
        user=user,
        purchase_order=purchase_order,
        data=merged,
        excluded_line_id=line.id,
    )

    if allocations_supplied:
        normalized_allocations = (
            _validate_purchase_order_line_allocations(
                db=db,
                purchase_order=purchase_order,
                allocations=allocations,
                ordered_quantity=prepared[
                    "ordered_quantity"
                ],
            )
        )
    else:
        current_total = sum(
            (
                Decimal(
                    str(
                        allocation
                        .allocated_quantity
                    )
                )
                for allocation in (
                    line.allocations or []
                )
            ),
            Decimal("0"),
        )

        if (
            current_total
            != Decimal(
                str(
                    prepared[
                        "ordered_quantity"
                    ]
                )
            )
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_LINE_ALLOCATION_INVALID,
                (
                    "Allocation changes are required "
                    "when ordered quantity changes"
                ),
            )

        normalized_allocations = None

    line.item_id = prepared["item_id"]
    line.ordered_quantity = prepared[
        "ordered_quantity"
    ]
    line.unit_id = prepared["unit_id"]
    line.line_description = prepared[
        "line_description"
    ]
    line.unit_price = prepared["unit_price"]
    line.currency_id = prepared["currency_id"]
    line.unit_price_base = prepared[
        "unit_price_base"
    ]
    line.exchange_rate_used = prepared[
        "exchange_rate_used"
    ]
    line.notes = prepared["notes"]

    if normalized_allocations is not None:
        for allocation in list(
            line.allocations or []
        ):
            db.delete(allocation)

        db.flush()

        for allocation in normalized_allocations:
            db.add(
                PurchasePhaseAllocation(
                    phase_id=(
                        allocation["phase_id"]
                    ),
                    purchase_order_line_id=(
                        line.id
                    ),
                    allocated_quantity=(
                        allocation[
                            "allocated_quantity"
                        ]
                    ),
                )
            )

    line_id = line.id
    db.commit()

    return _reload_purchase_order_line(
        db=db,
        purchase_order_id=purchase_order.id,
        line_id=line_id,
    )


def delete_purchase_order_line(
    db: Session,
    user: User,
    po_id: int,
    line_id: int,
) -> None:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    _assert_purchase_order_commercial_mutation_allowed(
        db=db,
        purchase_order=purchase_order,
    )

    line = _get_purchase_order_line_or_404(
        db=db,
        purchase_order_id=purchase_order.id,
        line_id=line_id,
    )

    db.delete(line)
    db.commit()


def cancel_purchase_order(db: Session, user: User, po_id: int) -> PurchaseOrder:
    po = get_po_or_404(db, po_id, user)
    po.status = PurchaseOrderStatus.CANCELLED.value
    db.commit()
    db.refresh(po)
    return po


def _assert_purchase_order_ready_for_submission(
    purchase_order: PurchaseOrder,
) -> None:
    lines = list(getattr(purchase_order, "lines", []) or [])
    phases = list(getattr(purchase_order, "phases", []) or [])

    if purchase_order.supplier_id is None:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            "Purchase order requires a supplier",
        )

    if not lines:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            "Purchase order requires at least one normalized line",
        )

    if not phases:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            "Purchase order requires at least one delivery phase",
        )

    phase_ids = {phase.id for phase in phases}
    currency_ids = {line.currency_id for line in lines}
    exchange_rates = {
        Decimal(str(line.exchange_rate_used))
        for line in lines
    }

    if len(currency_ids) != 1 or len(exchange_rates) != 1:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            "Purchase-order lines contain inconsistent commercial terms",
        )

    for line in lines:
        allocations = list(
            getattr(line, "allocations", []) or []
        )

        if not allocations:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_INVALID_STRUCTURE,
                f"Purchase-order line {line.line_number} has no delivery allocation",
            )

        if any(
            allocation.phase_id not in phase_ids
            for allocation in allocations
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_INVALID_STRUCTURE,
                f"Purchase-order line {line.line_number} has an invalid phase allocation",
            )

        allocated_quantity = sum(
            (
                Decimal(str(allocation.allocated_quantity))
                for allocation in allocations
            ),
            Decimal("0"),
        )

        if allocated_quantity != Decimal(
            str(line.ordered_quantity)
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_INVALID_STRUCTURE,
                f"Purchase-order line {line.line_number} allocation total does not equal ordered quantity",
            )


def process_approval(
    db: Session,
    user: User,
    po_id: int,
    action: str,
    note: Optional[str],
) -> PurchaseOrder:
    po = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    active_amendment = getattr(
        po,
        "active_amendment",
        None,
    )

    if active_amendment is not None:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
            (
                "Use the amendment approval "
                "workflow for this purchase order"
            ),
        )

    if action == "submit":
        if po.approval_status not in {
            PurchaseApprovalStatus.DRAFT.value,
            PurchaseApprovalStatus.REJECTED.value,
        }:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_APPROVAL_INVALID_TRANSITION,
                (
                    "Only draft or rejected orders "
                    "can be submitted for approval"
                ),
            )

        _assert_purchase_order_ready_for_submission(
            po
        )
        po.approval_status = (
            PurchaseApprovalStatus.PENDING.value
        )
        po.approved_by_user_id = None

    elif action == "approve":
        if (
            po.approval_status
            != PurchaseApprovalStatus.PENDING.value
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_APPROVAL_INVALID_TRANSITION,
                (
                    "Only pending orders "
                    "can be approved"
                ),
            )

        po.approval_status = (
            PurchaseApprovalStatus.APPROVED.value
        )
        po.status = (
            PurchaseOrderStatus.ORDERED.value
        )
        po.approved_by_user_id = user.id

        for phase in po.phases:
            if (
                phase.status
                == PurchasePhaseStatus.DRAFT.value
            ):
                phase.status = (
                    PurchasePhaseStatus.ORDERED.value
                )


        _synchronize_purchase_order_goods_prediction(
            db=db,
            user=user,
            purchase_order=po,
        )

    elif action == "reject":
        if (
            po.approval_status
            != PurchaseApprovalStatus.PENDING.value
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_APPROVAL_INVALID_TRANSITION,
                (
                    "Only pending orders "
                    "can be rejected"
                ),
            )

        po.approval_status = (
            PurchaseApprovalStatus.REJECTED.value
        )
        po.approved_by_user_id = None

    else:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_APPROVAL_ACTION_INVALID,
            f"Unknown approval action: {action}",
        )

    db.commit()
    db.refresh(po)

    return po


# ── PurchasePhase CRUD# ── PurchasePhase CRUD ────────────────────────────────────────────────────────

def list_phases(db: Session, user: User, po_id: int) -> List[PurchasePhase]:
    po = get_po_or_404(db, po_id, user)
    return po.phases


def add_phase(
    db: Session,
    user: User,
    po_id: int,
    title: Optional[str],
    description: Optional[str],
    currency_id: Optional[int],
    exchange_rate_used: Optional[Decimal],
    expected_delivery_date: Optional[datetime],
) -> PurchasePhase:
    po = get_po_or_404(db, po_id, user)
    phase_number = len(po.phases) + 1
    phase = PurchasePhase(
        purchase_order_id=po.id,
        phase_number=phase_number,
        title=title,
        description=description,
        status=PurchasePhaseStatus.DRAFT.value,
        currency_id=currency_id,
        exchange_rate_used=exchange_rate_used,
        expected_delivery_date=expected_delivery_date,
    )
    db.add(phase)
    db.commit()
    db.refresh(phase)
    return phase


def update_phase(db: Session, user: User, po_id: int, phase_id: int, **kwargs) -> PurchasePhase:
    po = get_po_or_404(db, po_id, user)
    phase = db.query(PurchasePhase).filter(
        PurchasePhase.id == phase_id,
        PurchasePhase.purchase_order_id == po.id,
    ).first()

    if not phase:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_NOT_FOUND,
            "Purchase phase not found",
        )

    for key, value in kwargs.items():
        if value is not None:
            setattr(phase, key, value)

    db.commit()
    db.refresh(phase)
    return phase


def _purchase_split_request_hash(
    data: dict,
) -> str:
    expected_delivery_date = data.get(
        "expected_delivery_date"
    )

    if hasattr(expected_delivery_date, "isoformat"):
        expected_delivery_date = (
            expected_delivery_date.isoformat()
        )

    canonical = {
        "title": (
            (data.get("title") or "").strip()
            or None
        ),
        "expected_delivery_date": (
            expected_delivery_date
        ),
        "reason": (
            (data.get("reason") or "").strip()
        ),
        "moves": sorted(
            [
                {
                    "from_phase_allocation_id": int(
                        move[
                            "from_phase_allocation_id"
                        ]
                    ),
                    "quantity": str(
                        Decimal(
                            str(move["quantity"])
                        ).normalize()
                    ),
                }
                for move in data.get("moves") or []
            ],
            key=lambda item: (
                item[
                    "from_phase_allocation_id"
                ]
            ),
        ),
    }

    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _normalized_idempotency_key(
    idempotency_key: str,
) -> str:
    normalized = (
        idempotency_key or ""
    ).strip()

    if not normalized:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_PHASE_SPLIT_IDEMPOTENCY_REQUIRED,
            "Idempotency-Key header is required",
        )

    if len(normalized) > 128:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_PHASE_SPLIT_IDEMPOTENCY_REQUIRED,
            "Idempotency-Key must not exceed "
            "128 characters",
        )

    return normalized


def _get_split_phase_result(
    db: Session,
    event: PurchasePhaseSplitEvent,
    replayed: bool,
) -> dict:
    phase = (
        db.query(PurchasePhase)
        .options(
            selectinload(
                PurchasePhase.allocations
            ),
            selectinload(
                PurchasePhase.items
            ),
        )
        .filter(
            PurchasePhase.id
            == event.target_phase_id,
            PurchasePhase.purchase_order_id
            == event.purchase_order_id,
        )
        .first()
    )

    if phase is None:
        purchase_error(
            status.HTTP_409_CONFLICT,
            PURCHASE_PHASE_SPLIT_INVALID_MOVE,
            "Split target phase was not found",
        )

    return {
        "phase": phase,
        "replayed": replayed,
        "audit_event_id": event.id,
    }


def get_purchase_order_split_candidates(
    db: Session,
    user: User,
    po_id: int,
    source_phase_id: Optional[int] = None,
    query_text: Optional[str] = None,
) -> list[dict]:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    query = (
        db.query(
            PurchasePhaseAllocation,
            PurchasePhase,
            PurchaseOrderLine,
        )
        .join(
            PurchasePhase,
            PurchasePhase.id
            == PurchasePhaseAllocation.phase_id,
        )
        .join(
            PurchaseOrderLine,
            PurchaseOrderLine.id
            == PurchasePhaseAllocation
            .purchase_order_line_id,
        )
        .filter(
            PurchasePhase.purchase_order_id
            == purchase_order.id,
            PurchaseOrderLine.purchase_order_id
            == purchase_order.id,
        )
    )

    if source_phase_id is not None:
        query = query.filter(
            PurchasePhase.id == source_phase_id
        )

    rows = (
        query.order_by(
            PurchasePhase.phase_number.asc(),
            PurchaseOrderLine.line_number.asc(),
            PurchasePhaseAllocation.id.asc(),
        )
        .all()
    )

    allocation_ids = [
        allocation.id
        for allocation, _, _ in rows
    ]

    from goods_receipt_management        .allocation_read_service import (
            get_allocation_receipt_usage,
        )
    from material_management.services import (
        get_item_reference,
        get_unit_or_404,
    )

    usage_by_id = (
        get_allocation_receipt_usage(
            db=db,
            allocation_ids=allocation_ids,
        )
    )

    normalized_query = (
        (query_text or "").strip().lower()
    )
    item_cache = {}
    unit_cache = {}
    result = []

    for allocation, phase, order_line in rows:
        usage = usage_by_id.get(
            allocation.id,
            {
                "posted_accepted_quantity": (
                    Decimal("0")
                ),
                "receipt_line_count": 0,
                "non_posted_line_count": 0,
            },
        )

        if usage["non_posted_line_count"] > 0:
            continue

        posted_quantity = Decimal(
            str(
                usage[
                    "posted_accepted_quantity"
                ]
            )
        )
        allocated_quantity = Decimal(
            str(allocation.allocated_quantity)
        )
        movable_quantity = (
            allocated_quantity
            - posted_quantity
        )

        if movable_quantity <= 0:
            continue

        if order_line.item_id not in item_cache:
            item_cache[order_line.item_id] = (
                get_item_reference(
                    db=db,
                    current_user=user,
                    item_id=order_line.item_id,
                )
            )

        if order_line.unit_id not in unit_cache:
            unit_cache[order_line.unit_id] = (
                get_unit_or_404(
                    db=db,
                    current_user=user,
                    unit_id=order_line.unit_id,
                )
            )

        item = item_cache[
            order_line.item_id
        ]
        unit = unit_cache[
            order_line.unit_id
        ]

        searchable = " ".join(
            str(value or "")
            for value in (
                item.get("item_code"),
                item.get("name"),
                order_line.line_description,
                order_line.line_number,
                phase.phase_number,
            )
        ).lower()

        if (
            normalized_query
            and normalized_query not in searchable
        ):
            continue

        result.append(
            {
                "from_phase_allocation_id": (
                    allocation.id
                ),
                "source_phase_id": phase.id,
                "source_phase_number": (
                    phase.phase_number
                ),
                "purchase_order_line_id": (
                    order_line.id
                ),
                "item_id": order_line.item_id,
                "item_code": item.get(
                    "item_code"
                ),
                "item_name": item["name"],
                "unit_code": unit.code,
                "ordered_quantity": (
                    order_line.ordered_quantity
                ),
                "allocated_quantity": (
                    allocated_quantity
                ),
                "posted_received_quantity": (
                    posted_quantity
                ),
                "movable_quantity": (
                    movable_quantity
                ),
            }
        )

    return result


def _refresh_split_receipt_statuses(
    db: Session,
    purchase_order: PurchaseOrder,
    source_phase_ids: list[int],
    emptied_source_phase_ids: set[int],
) -> None:
    from goods_receipt_management        .allocation_read_service import (
            get_allocation_receipt_usage,
        )

    source_phases = (
        db.query(PurchasePhase)
        .filter(
            PurchasePhase.id.in_(
                source_phase_ids
            ),
            PurchasePhase.purchase_order_id
            == purchase_order.id,
        )
        .order_by(PurchasePhase.id.asc())
        .with_for_update()
        .all()
    )

    remaining_source_allocations = (
        db.query(PurchasePhaseAllocation)
        .filter(
            PurchasePhaseAllocation.phase_id
            .in_(source_phase_ids)
        )
        .order_by(
            PurchasePhaseAllocation.id.asc()
        )
        .all()
    )

    allocations_by_phase = {}

    for allocation in remaining_source_allocations:
        allocations_by_phase.setdefault(
            allocation.phase_id,
            [],
        ).append(allocation)

    source_usage = get_allocation_receipt_usage(
        db=db,
        allocation_ids=[
            allocation.id
            for allocation
            in remaining_source_allocations
        ],
    )

    for phase in source_phases:
        phase_allocations = (
            allocations_by_phase.get(
                phase.id,
                [],
            )
        )

        if phase.id in emptied_source_phase_ids:
            phase.status = (
                PurchasePhaseStatus.CLOSED.value
            )
            continue

        if not phase_allocations:
            continue

        fully_received = all(
            Decimal(
                str(
                    source_usage.get(
                        allocation.id,
                        {},
                    ).get(
                        "posted_accepted_quantity",
                        0,
                    )
                )
            )
            >= Decimal(
                str(
                    allocation
                    .allocated_quantity
                )
            )
            for allocation in phase_allocations
        )

        has_receipts = any(
            Decimal(
                str(
                    source_usage.get(
                        allocation.id,
                        {},
                    ).get(
                        "posted_accepted_quantity",
                        0,
                    )
                )
            )
            > 0
            for allocation in phase_allocations
        )

        if fully_received:
            phase.status = (
                PurchasePhaseStatus.RECEIVED.value
            )
        elif has_receipts:
            phase.status = (
                PurchasePhaseStatus.SHIPPED.value
            )
        elif (
            purchase_order.status
            == PurchaseOrderStatus.DRAFT.value
        ):
            phase.status = (
                PurchasePhaseStatus.DRAFT.value
            )
        elif (
            phase.status
            != PurchasePhaseStatus.CLOSED.value
        ):
            phase.status = (
                PurchasePhaseStatus.ORDERED.value
            )

    order_allocations = (
        db.query(PurchasePhaseAllocation)
        .join(
            PurchasePhase,
            PurchasePhase.id
            == PurchasePhaseAllocation.phase_id,
        )
        .filter(
            PurchasePhase.purchase_order_id
            == purchase_order.id
        )
        .order_by(
            PurchasePhaseAllocation.id.asc()
        )
        .all()
    )

    order_usage = get_allocation_receipt_usage(
        db=db,
        allocation_ids=[
            allocation.id
            for allocation in order_allocations
        ],
    )

    order_has_receipts = any(
        Decimal(
            str(
                order_usage.get(
                    allocation.id,
                    {},
                ).get(
                    "posted_accepted_quantity",
                    0,
                )
            )
        )
        > 0
        for allocation in order_allocations
    )

    order_fully_received = (
        bool(order_allocations)
        and all(
            Decimal(
                str(
                    order_usage.get(
                        allocation.id,
                        {},
                    ).get(
                        "posted_accepted_quantity",
                        0,
                    )
                )
            )
            >= Decimal(
                str(
                    allocation
                    .allocated_quantity
                )
            )
            for allocation in order_allocations
        )
    )

    if order_fully_received:
        purchase_order.status = (
            PurchaseOrderStatus.RECEIVED.value
        )
    elif order_has_receipts:
        purchase_order.status = (
            PurchaseOrderStatus
            .PARTIALLY_RECEIVED.value
        )


def split_purchase_order_phase(
    db: Session,
    user: User,
    po_id: int,
    data: dict,
    idempotency_key: str,
) -> dict:
    company_id = _tenant_id(user)
    normalized_key = (
        _normalized_idempotency_key(
            idempotency_key
        )
    )
    request_hash = (
        _purchase_split_request_hash(data)
    )

    try:
        purchase_order = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.id == po_id,
                PurchaseOrder.company_id
                == company_id,
            )
            .with_for_update(of=PurchaseOrder)
            .first()
        )

        if purchase_order is None:
                        purchase_error(
                status.HTTP_404_NOT_FOUND,
                PURCHASE_ORDER_NOT_FOUND,
                "Purchase order not found",
            )

        existing_event = (
            db.query(PurchasePhaseSplitEvent)
            .filter(
                PurchasePhaseSplitEvent.company_id
                == company_id,
                PurchasePhaseSplitEvent
                .purchase_order_id
                == purchase_order.id,
                PurchasePhaseSplitEvent
                .idempotency_key
                == normalized_key,
            )
            .first()
        )

        if existing_event is not None:
            if (
                existing_event.request_hash
                != request_hash
            ):
                purchase_error(
                    status.HTTP_409_CONFLICT,
                    PURCHASE_PHASE_SPLIT_IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key was already used "
                    "with a different split request",
                )

            event_id = existing_event.id
            db.rollback()

            existing_event = (
                db.query(PurchasePhaseSplitEvent)
                .filter(
                    PurchasePhaseSplitEvent.id
                    == event_id,
                    PurchasePhaseSplitEvent.company_id
                    == company_id,
                )
                .first()
            )

            return _get_split_phase_result(
                db=db,
                event=existing_event,
                replayed=True,
            )

        if purchase_order.status in {
            PurchaseOrderStatus.CLOSED.value,
            PurchaseOrderStatus.CANCELLED.value,
        }:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_SPLIT_NOT_ALLOWED,
                "Closed or cancelled purchase "
                "orders cannot be split",
            )

        moves = list(data.get("moves") or [])

        if not moves:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                "At least one split move is required",
            )

        move_ids = [
            int(
                move[
                    "from_phase_allocation_id"
                ]
            )
            for move in moves
        ]

        if len(move_ids) != len(set(move_ids)):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                "Split moves contain duplicate "
                "source allocations",
            )

        allocations = (
            db.query(PurchasePhaseAllocation)
            .filter(
                PurchasePhaseAllocation.id.in_(
                    move_ids
                )
            )
            .order_by(
                PurchasePhaseAllocation.id.asc()
            )
            .with_for_update()
            .all()
        )

        if len(allocations) != len(move_ids):
            purchase_error(
                status.HTTP_404_NOT_FOUND,
                PURCHASE_PHASE_ALLOCATION_NOT_FOUND,
                "One or more source allocations "
                "were not found",
            )

        allocations_by_id = {
            allocation.id: allocation
            for allocation in allocations
        }
        source_phase_ids = sorted(
            {
                allocation.phase_id
                for allocation in allocations
            }
        )
        line_ids = sorted(
            {
                allocation
                .purchase_order_line_id
                for allocation in allocations
            }
        )

        source_phases = (
            db.query(PurchasePhase)
            .filter(
                PurchasePhase.id.in_(
                    source_phase_ids
                )
            )
            .order_by(PurchasePhase.id.asc())
            .with_for_update()
            .all()
        )
        lines = (
            db.query(PurchaseOrderLine)
            .filter(
                PurchaseOrderLine.id.in_(
                    line_ids
                )
            )
            .order_by(
                PurchaseOrderLine.id.asc()
            )
            .with_for_update()
            .all()
        )

        phases_by_id = {
            phase.id: phase
            for phase in source_phases
        }
        lines_by_id = {
            line.id: line
            for line in lines
        }

        if (
            len(phases_by_id)
            != len(source_phase_ids)
            or len(lines_by_id)
            != len(line_ids)
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                "A source phase or purchase-order "
                "line was not found",
            )

        for allocation in allocations:
            phase = phases_by_id[
                allocation.phase_id
            ]
            line = lines_by_id[
                allocation
                .purchase_order_line_id
            ]

            if (
                phase.purchase_order_id
                != purchase_order.id
                or line.purchase_order_id
                != purchase_order.id
            ):
                purchase_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                    "Every source allocation must "
                    "belong to the purchase order",
                )

        all_phases = (
            db.query(PurchasePhase)
            .filter(
                PurchasePhase.purchase_order_id
                == purchase_order.id
            )
            .order_by(PurchasePhase.id.asc())
            .with_for_update()
            .all()
        )

        next_phase_number = (
            max(
                (
                    phase.phase_number
                    for phase in all_phases
                ),
                default=0,
            )
            + 1
        )

        all_source_allocations = (
            db.query(PurchasePhaseAllocation)
            .filter(
                PurchasePhaseAllocation.phase_id
                .in_(source_phase_ids)
            )
            .order_by(
                PurchasePhaseAllocation.id.asc()
            )
            .with_for_update()
            .all()
        )

        from goods_receipt_management            .allocation_read_service import (
                get_allocation_receipt_usage,
            )

        usage_by_id = (
            get_allocation_receipt_usage(
                db=db,
                allocation_ids=move_ids,
            )
        )

        prepared_moves = []
        delete_ids_by_phase = {}
        target_quantity_by_line = {}

        for move in moves:
            allocation_id = int(
                move[
                    "from_phase_allocation_id"
                ]
            )
            quantity = Decimal(
                str(move["quantity"])
            )
            allocation = allocations_by_id[
                allocation_id
            ]
            usage = usage_by_id.get(
                allocation_id,
                {
                    "posted_accepted_quantity": (
                        Decimal("0")
                    ),
                    "receipt_line_count": 0,
                    "non_posted_line_count": 0,
                },
            )

            if quantity <= 0:
                purchase_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                    "Split quantities must be "
                    "greater than zero",
                )

            if usage[
                "non_posted_line_count"
            ] > 0:
                purchase_error(
                    status.HTTP_409_CONFLICT,
                    PURCHASE_PHASE_SPLIT_ALLOCATION_BLOCKED,
                    "The source allocation has an "
                    "unposted receipt and cannot be "
                    "rescheduled",
                )

            allocated_quantity = Decimal(
                str(
                    allocation
                    .allocated_quantity
                )
            )
            posted_quantity = Decimal(
                str(
                    usage[
                        "posted_accepted_quantity"
                    ]
                )
            )

            if posted_quantity > allocated_quantity:
                purchase_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    PURCHASE_PHASE_ALLOCATION_OVER_RECEIPT,
                    "Posted quantity exceeds the "
                    "source allocation",
                )

            movable_quantity = (
                allocated_quantity
                - posted_quantity
            )

            if quantity > movable_quantity:
                purchase_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    PURCHASE_PHASE_SPLIT_QUANTITY_EXCEEDS_MOVABLE,
                    "Split quantity exceeds the "
                    "movable allocation quantity",
                )

            new_source_quantity = (
                allocated_quantity
                - quantity
            )
            delete_source = (
                new_source_quantity == 0
                and posted_quantity == 0
                and usage[
                    "receipt_line_count"
                ] == 0
            )

            if (
                new_source_quantity
                < posted_quantity
            ):
                purchase_error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    PURCHASE_PHASE_SPLIT_QUANTITY_EXCEEDS_MOVABLE,
                    "Received quantity cannot be "
                    "moved",
                )

            if delete_source:
                delete_ids_by_phase.setdefault(
                    allocation.phase_id,
                    set(),
                ).add(allocation.id)

            target_quantity_by_line[
                allocation
                .purchase_order_line_id
            ] = (
                target_quantity_by_line.get(
                    allocation
                    .purchase_order_line_id,
                    Decimal("0"),
                )
                + quantity
            )

            prepared_moves.append(
                {
                    "allocation": allocation,
                    "moved_quantity": quantity,
                    "old_source_quantity": (
                        allocated_quantity
                    ),
                    "new_source_quantity": (
                        new_source_quantity
                    ),
                    "posted_quantity": (
                        posted_quantity
                    ),
                    "delete_source": (
                        delete_source
                    ),
                }
            )

        allocations_by_phase = {}

        for allocation in all_source_allocations:
            allocations_by_phase.setdefault(
                allocation.phase_id,
                [],
            ).append(allocation)

        emptied_source_phase_ids = {
            phase_id
            for phase_id, delete_ids
            in delete_ids_by_phase.items()
            if len(delete_ids)
            >= len(
                allocations_by_phase.get(
                    phase_id,
                    [],
                )
            )
        }

        phase_status = (
            PurchasePhaseStatus.DRAFT.value
            if purchase_order.status
            == PurchaseOrderStatus.DRAFT.value
            else PurchasePhaseStatus.ORDERED.value
        )

        target_phase = PurchasePhase(
            purchase_order_id=(
                purchase_order.id
            ),
            phase_number=next_phase_number,
            title=(
                (data.get("title") or "").strip()
                or f"Phase {next_phase_number}"
            ),
            description=None,
            status=phase_status,
            expected_delivery_date=data[
                "expected_delivery_date"
            ],
        )
        db.add(target_phase)
        db.flush()

        for prepared_move in prepared_moves:
            allocation = prepared_move[
                "allocation"
            ]

            if prepared_move[
                "delete_source"
            ]:
                db.delete(allocation)
            else:
                allocation.allocated_quantity = (
                    prepared_move[
                        "new_source_quantity"
                    ]
                )

        target_allocations = {}

        for line_id, quantity in sorted(
            target_quantity_by_line.items()
        ):
            target_allocation = (
                PurchasePhaseAllocation(
                    phase_id=target_phase.id,
                    purchase_order_line_id=(
                        line_id
                    ),
                    allocated_quantity=quantity,
                )
            )
            db.add(target_allocation)
            db.flush()

            target_allocations[
                line_id
            ] = target_allocation

        db.flush()

        _refresh_split_receipt_statuses(
            db=db,
            purchase_order=purchase_order,
            source_phase_ids=(
                source_phase_ids
            ),
            emptied_source_phase_ids=(
                emptied_source_phase_ids
            ),
        )

        allocation_totals = dict(
            db.query(
                PurchasePhaseAllocation
                .purchase_order_line_id,
                func.sum(
                    PurchasePhaseAllocation
                    .allocated_quantity
                ),
            )
            .filter(
                PurchasePhaseAllocation
                .purchase_order_line_id
                .in_(line_ids)
            )
            .group_by(
                PurchasePhaseAllocation
                .purchase_order_line_id
            )
            .all()
        )

        for line_id in line_ids:
            line = lines_by_id[line_id]
            total = Decimal(
                str(
                    allocation_totals.get(
                        line_id,
                        0,
                    )
                )
            )

            if total != Decimal(
                str(line.ordered_quantity)
            ):
                purchase_error(
                    status.HTTP_409_CONFLICT,
                    PURCHASE_PHASE_SPLIT_INVALID_MOVE,
                    "Split changed the total "
                    "allocated quantity",
                )

        move_details = []

        for prepared_move in prepared_moves:
            source_allocation = (
                prepared_move["allocation"]
            )
            target_allocation = (
                target_allocations[
                    source_allocation
                    .purchase_order_line_id
                ]
            )

            move_details.append(
                {
                    "from_phase_id": (
                        source_allocation.phase_id
                    ),
                    "from_phase_allocation_id": (
                        source_allocation.id
                    ),
                    "purchase_order_line_id": (
                        source_allocation
                        .purchase_order_line_id
                    ),
                    "old_source_quantity": str(
                        prepared_move[
                            "old_source_quantity"
                        ]
                    ),
                    "moved_quantity": str(
                        prepared_move[
                            "moved_quantity"
                        ]
                    ),
                    "new_source_quantity": str(
                        prepared_move[
                            "new_source_quantity"
                        ]
                    ),
                    "posted_received_quantity": str(
                        prepared_move[
                            "posted_quantity"
                        ]
                    ),
                    "source_allocation_removed": (
                        prepared_move[
                            "delete_source"
                        ]
                    ),
                    "source_phase_closed": (
                        source_allocation.phase_id
                        in emptied_source_phase_ids
                    ),
                    "target_phase_id": (
                        target_phase.id
                    ),
                    "target_phase_allocation_id": (
                        target_allocation.id
                    ),
                }
            )

        event = PurchasePhaseSplitEvent(
            company_id=company_id,
            purchase_order_id=(
                purchase_order.id
            ),
            target_phase_id=target_phase.id,
            idempotency_key=normalized_key,
            request_hash=request_hash,
            reason=(
                (data.get("reason") or "").strip()
            ),
            actor_user_id=user.id,
            details_json={
                "purchase_order_id": (
                    purchase_order.id
                ),
                "target_phase_id": (
                    target_phase.id
                ),
                "target_phase_number": (
                    target_phase.phase_number
                ),
                "reason": (
                    (data.get("reason") or "")
                    .strip()
                ),
                "closed_source_phase_ids": (
                    sorted(
                        emptied_source_phase_ids
                    )
                ),
                "moves": move_details,
            },
        )
        db.add(event)
        db.flush()
        db.commit()

        event_id = event.id

        event = (
            db.query(PurchasePhaseSplitEvent)
            .filter(
                PurchasePhaseSplitEvent.id
                == event_id,
                PurchasePhaseSplitEvent.company_id
                == company_id,
            )
            .first()
        )

        return _get_split_phase_result(
            db=db,
            event=event,
            replayed=False,
        )

    except Exception:
        db.rollback()
        raise



def _get_phase_or_404(db: Session, user: User, po_id: int, phase_id: int) -> PurchasePhase:
    po = get_po_or_404(db, po_id, user)
    phase = db.query(PurchasePhase).filter(
        PurchasePhase.id == phase_id,
        PurchasePhase.purchase_order_id == po.id,
    ).first()
    if not phase:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_NOT_FOUND,
            "Purchase phase not found",
        )
    return phase


def purchase_error(status_code: int, code: str, message: str):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def get_phase_reference_for_goods_receipt(
    db: Session,
    current_user: User,
    purchase_phase_id: int,
) -> dict:
    row = (
        db.query(PurchaseOrder, PurchasePhase)
        .join(
            PurchasePhase,
            PurchasePhase.purchase_order_id == PurchaseOrder.id,
        )
        .filter(
            PurchasePhase.id == purchase_phase_id,
            PurchaseOrder.company_id == _tenant_id(current_user),
        )
        .first()
    )

    if row is None:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_NOT_FOUND,
            "Purchase phase not found",
        )

    purchase_order, purchase_phase = row

    return {
        "purchase_order_id": purchase_order.id,
        "purchase_phase_id": purchase_phase.id,
    }


def get_phase_allocation_reference_for_goods_receipt(
    db: Session,
    current_user: User,
    purchase_order_id: int,
    purchase_phase_id: int,
    purchase_phase_allocation_id: int,
) -> dict:
    phase = _get_phase_or_404(
        db=db,
        user=current_user,
        po_id=purchase_order_id,
        phase_id=purchase_phase_id,
    )

    row = (
        db.query(
            PurchasePhaseAllocation,
            PurchaseOrderLine,
        )
        .join(
            PurchaseOrderLine,
            PurchaseOrderLine.id
            == PurchasePhaseAllocation.purchase_order_line_id,
        )
        .filter(
            PurchasePhaseAllocation.id
            == purchase_phase_allocation_id,
            PurchasePhaseAllocation.phase_id
            == phase.id,
            PurchaseOrderLine.purchase_order_id
            == purchase_order_id,
        )
        .first()
    )

    if row is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_ALLOCATION_NOT_FOUND,
            "Purchase phase allocation not found",
        )

    allocation, order_line = row

    purchase_order = get_po_or_404(
        db=db,
        po_id=purchase_order_id,
        user=current_user,
    )

    from goods_receipt_management.models import (
        GoodsReceiptItem,
        GoodsReceiptNote,
        GoodsReceiptStatus,
    )
    from material_management.services import (
        get_item_reference,
        get_unit_or_404,
    )

    item_reference = get_item_reference(
        db=db,
        current_user=current_user,
        item_id=order_line.item_id,
    )
    unit = get_unit_or_404(
        db=db,
        current_user=current_user,
        unit_id=order_line.unit_id,
    )

    received_quantity = (
        db.query(
            func.coalesce(
                func.sum(
                    GoodsReceiptItem.accepted_quantity
                ),
                0,
            )
        )
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem.goods_receipt_note_id,
        )
        .filter(
            GoodsReceiptItem.purchase_phase_allocation_id
            == allocation.id,
            GoodsReceiptNote.status
            == GoodsReceiptStatus.POSTED.value,
        )
        .scalar()
        or Decimal("0")
    )

    return {
        "id": allocation.id,
        "purchase_order_line_id": order_line.id,
        "item_id": order_line.item_id,
        "item_code": item_reference["item_code"],
        "item_name": item_reference["name"],
        "unit_id": order_line.unit_id,
        "unit_code": unit.code,
        "quantity": allocation.allocated_quantity,
        "received_quantity": received_quantity,
        "unit_price": order_line.unit_price,
        "currency_id": order_line.currency_id,
        "unit_price_base": order_line.unit_price_base,
        "base_currency_id": (
            _get_company_base_currency_reference(
                db=db,
                company_id=(
                    purchase_order.company_id
                ),
            ).id
        ),
        "exchange_rate_used": order_line.exchange_rate_used,
    }


def apply_goods_receipt(
    db: Session,
    current_user: User,
    purchase_order_id: int,
    purchase_phase_id: int,
    receipt_date: date,
    receipt_items: list[dict],
) -> None:
    from goods_receipt_management.models import (
        GoodsReceiptItem,
        GoodsReceiptNote,
        GoodsReceiptStatus,
    )

    purchase_order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.company_id
            == _tenant_id(current_user),
        )
        .with_for_update(of=PurchaseOrder)
        .first()
    )

    if purchase_order is None:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_NOT_FOUND,
            "Purchase order not found",
        )

    if purchase_order.status in {
        PurchaseOrderStatus.DRAFT.value,
        PurchaseOrderStatus.CANCELLED.value,
        PurchaseOrderStatus.CLOSED.value,
    }:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_NOT_RECEIVABLE,
            "Purchase order cannot receive goods "
            "in its current status",
        )

    phase = (
        db.query(PurchasePhase)
        .filter(
            PurchasePhase.id == purchase_phase_id,
            PurchasePhase.purchase_order_id
            == purchase_order.id,
        )
        .with_for_update()
        .first()
    )

    if phase is None:
                purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_NOT_FOUND,
            "Purchase phase not found",
        )

    if phase.status in {
        PurchasePhaseStatus.DRAFT.value,
        PurchasePhaseStatus.CLOSED.value,
    }:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_PHASE_NOT_RECEIVABLE,
            "Purchase phase cannot receive goods "
            "in its current status",
        )

    allocation_ids = [
        item["purchase_phase_allocation_id"]
        for item in receipt_items
    ]

    if len(allocation_ids) != len(set(allocation_ids)):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_PHASE_ALLOCATION_NOT_FOUND,
            "Receipt items contain duplicate allocations",
        )

    allocation_rows = (
        db.query(
            PurchasePhaseAllocation,
            PurchaseOrderLine,
        )
        .join(
            PurchaseOrderLine,
            PurchaseOrderLine.id
            == PurchasePhaseAllocation.purchase_order_line_id,
        )
        .filter(
            PurchasePhaseAllocation.phase_id
            == phase.id,
            PurchasePhaseAllocation.id.in_(
                allocation_ids
            ),
            PurchaseOrderLine.purchase_order_id
            == purchase_order.id,
        )
        .with_for_update()
        .all()
    )

    allocations_by_id = {
        allocation.id: allocation
        for allocation, _ in allocation_rows
    }

    if len(allocations_by_id) != len(set(allocation_ids)):
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_ALLOCATION_NOT_FOUND,
            "One or more purchase phase allocations "
            "were not found",
        )

    posted_totals = dict(
        db.query(
            GoodsReceiptItem.purchase_phase_allocation_id,
            func.sum(
                GoodsReceiptItem.accepted_quantity
            ),
        )
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem.goods_receipt_note_id,
        )
        .filter(
            GoodsReceiptItem.purchase_phase_allocation_id.in_(
                allocation_ids
            ),
            GoodsReceiptNote.status
            == GoodsReceiptStatus.POSTED.value,
        )
        .group_by(
            GoodsReceiptItem.purchase_phase_allocation_id
        )
        .all()
    )

    for allocation_id in allocation_ids:
        allocation = allocations_by_id[allocation_id]
        received_quantity = Decimal(
            str(posted_totals.get(allocation_id, 0))
        )

        if received_quantity > Decimal(
            str(allocation.allocated_quantity)
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_ALLOCATION_OVER_RECEIPT,
                "Posted accepted quantity exceeds "
                "the phase allocation quantity",
            )

    phase_allocations = (
        db.query(PurchasePhaseAllocation)
        .filter(
            PurchasePhaseAllocation.phase_id
            == phase.id
        )
        .all()
    )

    phase_allocation_ids = [
        allocation.id
        for allocation in phase_allocations
    ]

    phase_totals = dict(
        db.query(
            GoodsReceiptItem.purchase_phase_allocation_id,
            func.sum(
                GoodsReceiptItem.accepted_quantity
            ),
        )
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem.goods_receipt_note_id,
        )
        .filter(
            GoodsReceiptItem.purchase_phase_allocation_id.in_(
                phase_allocation_ids
            ),
            GoodsReceiptNote.status
            == GoodsReceiptStatus.POSTED.value,
        )
        .group_by(
            GoodsReceiptItem.purchase_phase_allocation_id
        )
        .all()
    )

    phase_is_complete = (
        bool(phase_allocations)
        and all(
            Decimal(
                str(
                    phase_totals.get(
                        allocation.id,
                        0,
                    )
                )
            )
            >= Decimal(
                str(allocation.allocated_quantity)
            )
            for allocation in phase_allocations
        )
    )

    phase_has_receipts = any(
        Decimal(
            str(
                phase_totals.get(
                    allocation.id,
                    0,
                )
            )
        )
        > 0
        for allocation in phase_allocations
    )

    if phase_is_complete:
        phase.status = PurchasePhaseStatus.RECEIVED.value
    elif (
        phase_has_receipts
        and phase.status
        == PurchasePhaseStatus.ORDERED.value
    ):
        phase.status = PurchasePhaseStatus.SHIPPED.value

    order_allocations = (
        db.query(PurchasePhaseAllocation)
        .join(
            PurchasePhase,
            PurchasePhase.id
            == PurchasePhaseAllocation.phase_id,
        )
        .filter(
            PurchasePhase.purchase_order_id
            == purchase_order.id
        )
        .all()
    )

    order_allocation_ids = [
        allocation.id
        for allocation in order_allocations
    ]

    order_totals = dict(
        db.query(
            GoodsReceiptItem.purchase_phase_allocation_id,
            func.sum(
                GoodsReceiptItem.accepted_quantity
            ),
        )
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem.goods_receipt_note_id,
        )
        .filter(
            GoodsReceiptItem.purchase_phase_allocation_id.in_(
                order_allocation_ids
            ),
            GoodsReceiptNote.status
            == GoodsReceiptStatus.POSTED.value,
        )
        .group_by(
            GoodsReceiptItem.purchase_phase_allocation_id
        )
        .all()
    )

    order_is_complete = (
        bool(order_allocations)
        and all(
            Decimal(
                str(
                    order_totals.get(
                        allocation.id,
                        0,
                    )
                )
            )
            >= Decimal(
                str(allocation.allocated_quantity)
            )
            for allocation in order_allocations
        )
    )

    order_has_receipts = any(
        Decimal(
            str(
                order_totals.get(
                    allocation.id,
                    0,
                )
            )
        )
        > 0
        for allocation in order_allocations
    )

    if order_is_complete:
        purchase_order.status = (
            PurchaseOrderStatus.RECEIVED.value
        )
    elif order_has_receipts:
        purchase_order.status = (
            PurchaseOrderStatus.PARTIALLY_RECEIVED.value
        )


# ── PurchaseOrderCost ─────────────────────────────────────────────────────────

PURCHASE_ORDER_COST_TYPES = {
    "goods",
    "freight",
    "customs",
    "tax",
    "insurance",
    "other",
}


def _normalize_purchase_order_cost_type(
    cost_type: str,
) -> str:
    normalized = str(
        cost_type or ""
    ).strip().lower()

    if (
        normalized
        not in PURCHASE_ORDER_COST_TYPES
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COST_TYPE_INVALID,
            "Invalid purchase-order cost type",
        )

    return normalized


def _prepare_purchase_order_cost_money_bundle(
    db: Session,
    purchase_order: PurchaseOrder,
    *,
    amount,
    currency_id,
) -> dict:
    if (
        amount is None
        or currency_id is None
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COST_MONEY_INCOMPLETE,
            (
                "Cost amount and currency "
                "must be provided together"
            ),
        )

    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=(
                purchase_order.company_id
            ),
        )
    )

    currency = get_currency_or_404(
        db=db,
        currency_id=int(currency_id),
    )

    if not currency.is_active:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_CURRENCY_INVALID,
            (
                "Purchase-order cost "
                "currency is inactive"
            ),
        )

    normalized_amount = quantize_money(
        amount,
        currency.decimal_places,
    )

    if currency.id == base_currency.id:
        exchange_rate = Decimal("1")
    else:
        exchange_rate = get_rate(
            db=db,
            from_code=currency.code,
            to_code=base_currency.code,
            on_date=date.today(),
        )

        if exchange_rate is None:
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COST_MONEY_INCOMPLETE,
                (
                    "No exchange rate is "
                    "available for the "
                    "purchase-order cost"
                ),
            )

    normalized_rate = (
        quantize_exchange_rate(
            exchange_rate
        )
    )

    amount_base = quantize_money(
        normalized_amount
        * normalized_rate,
        base_currency.decimal_places,
    )

    return {
        "amount": normalized_amount,
        "currency_id": currency.id,
        "amount_base": amount_base,
        "base_currency_id": (
            base_currency.id
        ),
        "exchange_rate_used": (
            normalized_rate
        ),
    }


def _get_purchase_order_cost_paid_base(
    db: Session,
    user: User,
    cost_id: int,
) -> Decimal:
    from financial_management.services import (
        get_purchase_cost_payment_summaries,
    )

    summaries = (
        get_purchase_cost_payment_summaries(
            db=db,
            current_user=user,
            cost_ids=[cost_id],
        )
    )

    summary = summaries.get(cost_id)

    if summary is None:
        return Decimal("0")

    return Decimal(
        str(
            summary.get(
                "paid_base",
                Decimal("0"),
            )
        )
    )


GOODS_PREDICTION_DESCRIPTION = (
    "Derived purchase-order line total"
)


def _build_purchase_order_goods_prediction_bundle(
    db: Session,
    purchase_order: PurchaseOrder,
) -> dict:
    lines = list(
        getattr(
            purchase_order,
            "lines",
            [],
        )
        or []
    )

    if not lines:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            (
                "Purchase order requires at "
                "least one normalized line"
            ),
        )

    currency_ids = {
        int(line.currency_id)
        for line in lines
    }

    exchange_rates = {
        quantize_exchange_rate(
            Decimal(
                str(
                    line.exchange_rate_used
                )
            )
        )
        for line in lines
    }

    if (
        len(currency_ids) != 1
        or len(exchange_rates) != 1
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            (
                "Purchase-order lines contain "
                "inconsistent commercial terms"
            ),
        )

    currency_id = next(
        iter(currency_ids)
    )

    exchange_rate = next(
        iter(exchange_rates)
    )

    currency = get_currency_or_404(
        db=db,
        currency_id=currency_id,
    )

    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=(
                purchase_order.company_id
            ),
        )
    )

    amount = quantize_money(
        sum(
            (
                Decimal(
                    str(
                        line.ordered_quantity
                    )
                )
                * Decimal(
                    str(
                        line.unit_price
                    )
                )
                for line in lines
            ),
            Decimal("0"),
        ),
        int(currency.decimal_places),
    )

    amount_base = quantize_money(
        sum(
            (
                Decimal(
                    str(
                        line.ordered_quantity
                    )
                )
                * Decimal(
                    str(
                        line.unit_price_base
                    )
                )
                for line in lines
            ),
            Decimal("0"),
        ),
        int(base_currency.decimal_places),
    )

    return {
        "amount": amount,
        "currency_id": currency.id,
        "amount_base": amount_base,
        "base_currency_id": (
            base_currency.id
        ),
        "exchange_rate_used": (
            exchange_rate
        ),
    }


def _apply_goods_prediction_bundle(
    cost: PurchaseOrderCost,
    bundle: dict,
) -> None:
    cost.cost_type = "goods"
    cost.description = (
        GOODS_PREDICTION_DESCRIPTION
    )

    cost.amount = bundle["amount"]
    cost.currency_id = bundle[
        "currency_id"
    ]
    cost.amount_base = bundle[
        "amount_base"
    ]
    cost.base_currency_id = bundle[
        "base_currency_id"
    ]
    cost.exchange_rate_used = bundle[
        "exchange_rate_used"
    ]
    cost.allocation_method = (
        CostAllocationMethod
        .PER_VALUE
        .value
    )

    cost.predicted_amount = bundle[
        "amount"
    ]
    cost.predicted_currency_id = bundle[
        "currency_id"
    ]
    cost.predicted_amount_base = bundle[
        "amount_base"
    ]
    cost.predicted_exchange_rate_used = (
        bundle[
            "exchange_rate_used"
        ]
    )


def _goods_prediction_differs(
    cost: PurchaseOrderCost,
    bundle: dict,
) -> bool:
    values = (
        (
            cost.predicted_amount,
            bundle["amount"],
        ),
        (
            cost.predicted_currency_id,
            bundle["currency_id"],
        ),
        (
            cost.predicted_amount_base,
            bundle["amount_base"],
        ),
        (
            cost.predicted_exchange_rate_used,
            bundle[
                "exchange_rate_used"
            ],
        ),
        (
            cost.base_currency_id,
            bundle["base_currency_id"],
        ),
    )

    for current, expected in values:
        if current is None:
            return True

        if isinstance(
            expected,
            Decimal,
        ):
            if (
                Decimal(str(current))
                != Decimal(str(expected))
            ):
                return True
        elif int(current) != int(expected):
            return True

    return False


def _synchronize_purchase_order_goods_prediction(
    db: Session,
    user: User,
    purchase_order: PurchaseOrder,
) -> str:
    bundle = (
        _build_purchase_order_goods_prediction_bundle(
            db=db,
            purchase_order=purchase_order,
        )
    )

    goods_costs = sorted(
        [
            cost
            for cost in (
                getattr(
                    purchase_order,
                    "costs",
                    [],
                )
                or []
            )
            if str(cost.cost_type) == "goods"
        ],
        key=lambda cost: (
            cost.id or 0
        ),
    )

    if len(goods_costs) > 1:
        purchase_error(
            status.HTTP_409_CONFLICT,
            (
                PURCHASE_ORDER_COST_NOT_FINANCIALLY_EDITABLE
            ),
            (
                "Purchase order contains "
                "multiple goods predictions"
            ),
        )

    if not goods_costs:
        cost = PurchaseOrderCost(
            purchase_order_id=(
                purchase_order.id
            ),
            cost_type="goods",
            description=(
                GOODS_PREDICTION_DESCRIPTION
            ),
            amount=bundle["amount"],
            currency_id=bundle[
                "currency_id"
            ],
            amount_base=bundle[
                "amount_base"
            ],
            base_currency_id=bundle[
                "base_currency_id"
            ],
            exchange_rate_used=bundle[
                "exchange_rate_used"
            ],
            allocation_method=(
                CostAllocationMethod
                .PER_VALUE
                .value
            ),
            predicted_amount=bundle[
                "amount"
            ],
            predicted_currency_id=bundle[
                "currency_id"
            ],
            predicted_amount_base=bundle[
                "amount_base"
            ],
            predicted_exchange_rate_used=(
                bundle[
                    "exchange_rate_used"
                ]
            ),
            created_by_user_id=user.id,
        )

        db.add(cost)

        costs = getattr(
            purchase_order,
            "costs",
            None,
        )

        if (
            isinstance(costs, list)
            and cost not in costs
        ):
            costs.append(cost)

        return "synced"

    cost = goods_costs[0]

    paid_base = (
        _get_purchase_order_cost_paid_base(
            db=db,
            user=user,
            cost_id=cost.id,
        )
    )

    protected = (
        cost.actual_amount_base
        is not None
        or paid_base > 0
    )

    differs = _goods_prediction_differs(
        cost=cost,
        bundle=bundle,
    )

    if protected and differs:
        return "payment_review_required"

    if differs:
        _apply_goods_prediction_bundle(
            cost=cost,
            bundle=bundle,
        )

    return "synced"


def _derived_purchase_order_goods_total_base(
    purchase_order: PurchaseOrder,
    decimal_places: int,
) -> Decimal:
    return quantize_money(
        sum(
            (
                Decimal(
                    str(
                        line.ordered_quantity
                    )
                )
                * Decimal(
                    str(
                        line.unit_price_base
                    )
                )
                for line in (
                    getattr(
                        purchase_order,
                        "lines",
                        [],
                    )
                    or []
                )
            ),
            Decimal("0"),
        ),
        decimal_places,
    )


def list_purchase_order_costs(
    db: Session,
    user: User,
    po_id: int,
) -> list[PurchaseOrderCost]:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    return (
        db.query(PurchaseOrderCost)
        .filter(
            PurchaseOrderCost
            .purchase_order_id
            == purchase_order.id,
        )
        .order_by(
            PurchaseOrderCost.id.asc()
        )
        .all()
    )


def get_purchase_order_cost(
    db: Session,
    user: User,
    po_id: int,
    cost_id: int,
) -> PurchaseOrderCost:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    return _get_purchase_order_cost_or_404(
        db=db,
        purchase_order_id=(
            purchase_order.id
        ),
        cost_id=cost_id,
    )

def add_cost(
    db: Session,
    user: User,
    po_id: int,
    cost_type: str,
    description: Optional[str],
    predicted_amount: Decimal,
    predicted_currency_id: int,
) -> PurchaseOrderCost:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    normalized_type = (
        _normalize_purchase_order_cost_type(
            cost_type
        )
    )

    if (
        normalized_type == "goods"
        and any(
            str(cost.cost_type) == "goods"
            for cost in (
                purchase_order.costs or []
            )
        )
    ):
        purchase_error(
            status.HTTP_409_CONFLICT,
            (
                PURCHASE_ORDER_COST_NOT_FINANCIALLY_EDITABLE
            ),
            (
                "Purchase order already has "
                "a goods prediction"
            ),
        )

    predicted = (
        _prepare_purchase_order_cost_money_bundle(
            db=db,
            purchase_order=purchase_order,
            amount=predicted_amount,
            currency_id=(
                predicted_currency_id
            ),
        )
    )

    cost = PurchaseOrderCost(
        purchase_order_id=(
            purchase_order.id
        ),
        cost_type=normalized_type,
        description=(
            (
                description or ""
            ).strip()
            or None
        ),
        amount=predicted["amount"],
        currency_id=(
            predicted["currency_id"]
        ),
        amount_base=(
            predicted["amount_base"]
        ),
        base_currency_id=(
            predicted["base_currency_id"]
        ),
        exchange_rate_used=(
            predicted[
                "exchange_rate_used"
            ]
        ),
        allocation_method=(
            CostAllocationMethod
            .PER_VALUE
            .value
        ),
        predicted_amount=(
            predicted["amount"]
        ),
        predicted_currency_id=(
            predicted["currency_id"]
        ),
        predicted_amount_base=(
            predicted["amount_base"]
        ),
        predicted_exchange_rate_used=(
            predicted[
                "exchange_rate_used"
            ]
        ),
        created_by_user_id=user.id,
    )

    db.add(cost)
    db.commit()
    db.refresh(cost)

    return cost



def update_cost(
    db: Session,
    user: User,
    po_id: int,
    cost_id: int,
    data: dict,
) -> PurchaseOrderCost:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    cost = _get_purchase_order_cost_or_404(
        db=db,
        purchase_order_id=(
            purchase_order.id
        ),
        cost_id=cost_id,
    )

    paid_base = (
        _get_purchase_order_cost_paid_base(
            db=db,
            user=user,
            cost_id=cost.id,
        )
    )

    if "cost_type" in data:
        normalized_type = (
            _normalize_purchase_order_cost_type(
                data["cost_type"]
            )
        )

        if (
            paid_base > 0
            and normalized_type
            != cost.cost_type
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COST_HAS_PAYMENTS,
                (
                    "Cost type cannot be "
                    "changed after payment"
                ),
            )

        cost.cost_type = normalized_type

    if "description" in data:
        cost.description = (
            (
                data["description"] or ""
            ).strip()
            or None
        )

    predicted_change = any(
        key in data
        for key in (
            "predicted_amount",
            "predicted_currency_id",
        )
    )

    if predicted_change:
        predicted_amount = data.get(
            "predicted_amount",
            cost.predicted_amount,
        )
        predicted_currency_id = data.get(
            "predicted_currency_id",
            cost.predicted_currency_id,
        )

        if (
            predicted_amount is None
            or predicted_currency_id
            is None
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COST_MONEY_INCOMPLETE,
                (
                    "Predicted amount and "
                    "currency must be "
                    "provided together"
                ),
            )

        if (
            paid_base > 0
            and int(
                predicted_currency_id
            )
            != int(
                cost.predicted_currency_id
            )
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_COST_HAS_PAYMENTS,
                (
                    "Cost currency cannot "
                    "be changed after payment"
                ),
            )

        predicted = (
            _prepare_purchase_order_cost_money_bundle(
                db=db,
                purchase_order=(
                    purchase_order
                ),
                amount=predicted_amount,
                currency_id=(
                    predicted_currency_id
                ),
            )
        )

        candidate_target_base = (
            Decimal(
                str(
                    cost.actual_amount_base
                )
            )
            if (
                cost.actual_amount_base
                is not None
            )
            else Decimal(
                str(
                    predicted[
                        "amount_base"
                    ]
                )
            )
        )

        if (
            paid_base > 0
            and candidate_target_base
            < paid_base
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                (
                    PURCHASE_ORDER_COST_NOT_FINANCIALLY_EDITABLE
                ),
                (
                    "Cost target cannot be "
                    "reduced below the paid "
                    "amount"
                ),
            )

        cost.predicted_amount = (
            predicted["amount"]
        )
        cost.predicted_currency_id = (
            predicted["currency_id"]
        )
        cost.predicted_amount_base = (
            predicted["amount_base"]
        )
        cost.predicted_exchange_rate_used = (
            predicted[
                "exchange_rate_used"
            ]
        )

        cost.amount = predicted["amount"]
        cost.currency_id = (
            predicted["currency_id"]
        )
        cost.amount_base = (
            predicted["amount_base"]
        )
        cost.base_currency_id = (
            predicted["base_currency_id"]
        )
        cost.exchange_rate_used = (
            predicted[
                "exchange_rate_used"
            ]
        )

    db.commit()
    db.refresh(cost)

    return cost



def delete_cost(
    db: Session,
    user: User,
    po_id: int,
    cost_id: int,
) -> None:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    cost = _get_purchase_order_cost_or_404(
        db=db,
        purchase_order_id=(
            purchase_order.id
        ),
        cost_id=cost_id,
    )

    paid_base = (
        _get_purchase_order_cost_paid_base(
            db=db,
            user=user,
            cost_id=cost.id,
        )
    )

    if paid_base > 0:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COST_HAS_PAYMENTS,
            (
                "A paid purchase-order "
                "cost cannot be deleted"
            ),
        )

    db.delete(cost)
    db.commit()



# ── Receipt link ──────────────────────────────────────────────────────────────

def add_receipt_link(
    db: Session,
    user: User,
    po_id: int,
    financial_receipt_id: int,
) -> PurchaseOrderReceiptLink:
    po = get_po_or_404(db, po_id, user)
    link = PurchaseOrderReceiptLink(
        purchase_order_id=po.id,
        financial_receipt_id=financial_receipt_id,
        linked_by_user_id=user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


# ── Summary ───────────────────────────────────────────────────────────────────

def _purchase_order_has_untracked_legacy_payments(
    db: Session,
    purchase_order_id: int,
) -> bool:
    return (
        db.query(
            PurchaseOrderReceiptLink.id
        )
        .filter(
            PurchaseOrderReceiptLink
            .purchase_order_id
            == purchase_order_id,
            PurchaseOrderReceiptLink
            .allocation_status
            == "legacy_unallocated",
        )
        .first()
        is not None
    )


def _purchase_order_cost_payment_state(
    *,
    payment_tracking: str,
    actual_confirmed: bool,
    settlement_target_base: Decimal,
    paid_base: Decimal,
    review_required: bool = False,
) -> str:
    if review_required:
        return "payment_review_required"

    if payment_tracking == "not_tracked":
        return "not_tracked"

    if paid_base > settlement_target_base:
        return "payment_review_required"

    if not actual_confirmed and paid_base > 0:
        return "advance_paid"

    if paid_base == 0:
        if (
            actual_confirmed
            and settlement_target_base == 0
        ):
            return "paid"

        return "unpaid"

    if paid_base < settlement_target_base:
        return "partially_paid"

    return "paid"


def get_purchase_order_payment_summary(
    db: Session,
    user: User,
    po_id: int,
) -> dict:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=(
                purchase_order.company_id
            ),
        )
    )

    costs = sorted(
        list(
            purchase_order.costs or []
        ),
        key=lambda cost: (
            cost.id or 0
        ),
    )

    cost_ids = [
        int(cost.id)
        for cost in costs
        if cost.id is not None
    ]

    from financial_management.services import (
        get_purchase_cost_payment_summaries,
    )

    paid_summaries = (
        get_purchase_cost_payment_summaries(
            db=db,
            current_user=user,
            cost_ids=cost_ids,
        )
    )

    payment_tracking = (
        "not_tracked"
        if (
            _purchase_order_has_untracked_legacy_payments(
                db=db,
                purchase_order_id=(
                    purchase_order.id
                ),
            )
        )
        else "tracked"
    )

    decimal_places = int(
        base_currency.decimal_places
    )

    zero = quantize_money(
        Decimal("0"),
        decimal_places,
    )

    derived_goods_total_base = (
        _derived_purchase_order_goods_total_base(
            purchase_order=purchase_order,
            decimal_places=decimal_places,
        )
    )

    cost_types = (
        "goods",
        "freight",
        "customs",
        "tax",
        "insurance",
        "other",
    )

    predicted_by_cost_type = {
        cost_type: zero
        for cost_type in cost_types
    }

    predicted_total = zero
    actual_total = zero
    unpredicted_total = zero
    paid_total = zero
    outstanding_total = zero
    variance_total = zero

    cost_rows = []

    for cost in costs:
        predicted_base = (
            quantize_money(
                Decimal(
                    str(
                        cost
                        .predicted_amount_base
                    )
                ),
                decimal_places,
            )
            if (
                cost.predicted_amount_base
                is not None
            )
            else zero
        )

        actual_confirmed = (
            cost.actual_amount_base
            is not None
        )

        actual_base = (
            quantize_money(
                Decimal(
                    str(
                        cost.actual_amount_base
                    )
                ),
                decimal_places,
            )
            if actual_confirmed
            else zero
        )

        settlement_target = (
            actual_base
            if actual_confirmed
            else predicted_base
        )

        paid_summary = (
            paid_summaries.get(
                int(cost.id),
                {},
            )
            if cost.id is not None
            else {}
        )

        paid_base = quantize_money(
            Decimal(
                str(
                    paid_summary.get(
                        "paid_base",
                        Decimal("0"),
                    )
                )
            ),
            decimal_places,
        )

        outstanding_base = (
            quantize_money(
                settlement_target
                - paid_base,
                decimal_places,
            )
        )

        variance_base = None

        if actual_confirmed:
            variance_base = (
                quantize_money(
                    actual_base
                    - predicted_base,
                    decimal_places,
                )
            )

        cost_type = str(
            cost.cost_type
        )

        predicted_total = (
            quantize_money(
                predicted_total
                + predicted_base,
                decimal_places,
            )
        )

        predicted_by_cost_type[
            cost_type
        ] = quantize_money(
            predicted_by_cost_type.get(
                cost_type,
                zero,
            )
            + predicted_base,
            decimal_places,
        )

        actual_total = quantize_money(
            actual_total + actual_base,
            decimal_places,
        )

        if (
            actual_confirmed
            and cost.predicted_amount_base
            is None
        ):
            unpredicted_total = (
                quantize_money(
                    unpredicted_total
                    + actual_base,
                    decimal_places,
                )
            )

        paid_total = quantize_money(
            paid_total + paid_base,
            decimal_places,
        )

        outstanding_total = (
            quantize_money(
                outstanding_total
                + outstanding_base,
                decimal_places,
            )
        )

        if variance_base is not None:
            variance_total = (
                quantize_money(
                    variance_total
                    + variance_base,
                    decimal_places,
                )
            )

        cost_rows.append(
            {
                "cost_id": cost.id,
                "settlement_target_base": (
                    settlement_target
                ),
                "paid_base": paid_base,
                "outstanding_base": (
                    outstanding_base
                ),
                "variance_base": (
                    variance_base
                ),
                "payment_state": (
                    _purchase_order_cost_payment_state(
                        payment_tracking=(
                            payment_tracking
                        ),
                        actual_confirmed=(
                            actual_confirmed
                        ),
                        settlement_target_base=(
                            settlement_target
                        ),
                        paid_base=paid_base,
                        review_required=(
                            cost_type == "goods"
                            and (
                                actual_confirmed
                                or paid_base > 0
                            )
                            and (
                                predicted_base
                                != derived_goods_total_base
                            )
                        ),
                    )
                ),
            }
        )

    return {
        "purchase_order_id": (
            purchase_order.id
        ),
        "base_currency_id": (
            base_currency.id
        ),
        "predicted_total_base": (
            predicted_total
        ),
        "predicted_by_cost_type_base": (
            predicted_by_cost_type
        ),
        "actual_total_base": actual_total,
        "unpredicted_total_base": (
            unpredicted_total
        ),
        "paid_total_base": paid_total,
        "outstanding_total_base": (
            outstanding_total
        ),
        "variance_total_base": (
            variance_total
        ),
        "payment_tracking": (
            payment_tracking
        ),
        "costs": cost_rows,
    }


def get_summary(
    db: Session,
    user: User,
    po_id: int,
) -> dict:
    po = get_po_or_404(
        db,
        po_id,
        user,
    )
    lines = list(po.lines or [])

    base_currency = (
        _get_company_base_currency_reference(
            db=db,
            company_id=po.company_id,
        )
    )

    item_count = len(lines)

    total_in_currency = sum(
        (
            Decimal(
                str(line.ordered_quantity)
            )
            * Decimal(
                str(line.unit_price)
            )
            for line in lines
        ),
        Decimal("0"),
    )

    total_in_base = sum(
        (
            Decimal(
                str(line.ordered_quantity)
            )
            * Decimal(
                str(line.unit_price_base)
            )
            for line in lines
        ),
        Decimal("0"),
    )

    additional_costs_base = sum(
        (
            Decimal(
                str(cost.amount_base)
            )
            for cost in po.costs
            if str(cost.cost_type) != "goods"
        ),
        Decimal("0"),
    )

    return {
        "purchase_order_id": po.id,
        "reference_number": (
            po.reference_number
        ),
        "phase_count": len(
            po.phases
        ),
        "item_count": item_count,
        "total_in_currency": (
            total_in_currency
        ),
        "total_in_base": total_in_base,
        "currency_id": (
            lines[0].currency_id
            if lines
            else None
        ),
        "base_currency_id": (
            base_currency.id
        ),
        "additional_costs_base": (
            additional_costs_base
        ),
        "grand_total_base": (
            total_in_base
            + additional_costs_base
        ),
    }


# ── Embedding# ── Embedding ─────────────────────────────────────────────────────────────────

def ensure_po_embeddings(db: Session, user: User, po_ids: Optional[List[int]] = None) -> None:
    """Generate missing description embeddings for PurchaseOrders."""
    try:
        from components.embedding import JinaAPIEmbeddings
        client = JinaAPIEmbeddings()

        q = (
            db.query(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.supplier)
            )
            .filter(
                PurchaseOrder.company_id == _tenant_id(user),
            PurchaseOrder.description_embedding == None,
                PurchaseOrder.description != None,
            )
        )
        if po_ids:
            q = q.filter(PurchaseOrder.id.in_(po_ids))

        for po in q.limit(50).all():
            text = _build_searchable_text(po)
            if not text:
                continue
            embedding = client.embed_query(text)
            if embedding:
                po.description_embedding = embedding
        db.commit()
    except Exception:
        pass  # Graceful degradation — search will fall back to keyword


def _build_searchable_text(po: PurchaseOrder) -> str:
    parts = [
        po.reference_number or "",
        po.supplier_name or "",
        po.title or "",
        po.description or "",
    ]
    return " ".join(p for p in parts if p).strip()




def _supplier_ids_matching_query(
    db: Session,
    current_user: User,
    query_text: str,
) -> list[int]:
    from supplier_management.search.service import (
        search_supplier_hits,
    )

    try:
        hits = search_supplier_hits(
            db=db,
            current_user=current_user,
            query_text=query_text,
            mode="keyword",
            limit=100,
        )
    except Exception:
        return []

    supplier_ids: list[int] = []

    for hit in hits:
        value = getattr(
            hit,
            "id",
            getattr(hit, "supplier_id", None),
        )

        if value is not None:
            supplier_ids.append(int(value))

    return list(dict.fromkeys(supplier_ids))

def export_purchase_order_rows(
    db: Session,
    current_user: User,
    query_text: Optional[str] = None,
    po_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    limit: int = 10000,
) -> list[dict]:
    from sqlalchemy import or_
    from sqlalchemy.orm import selectinload

    query = (
        db.query(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.lines),
            selectinload(PurchaseOrder.phases),
            selectinload(PurchaseOrder.costs),
        )
        .filter(
            PurchaseOrder.company_id
            == _tenant_id(current_user)
        )
    )

    if po_status:
        query = query.filter(
            PurchaseOrder.status == po_status
        )

    if approval_status:
        query = query.filter(
            PurchaseOrder.approval_status
            == approval_status
        )

    if query_text:
        normalized_query = query_text.strip()
        pattern = f"%{normalized_query}%"
        supplier_ids = _supplier_ids_matching_query(
            db=db,
            current_user=current_user,
            query_text=normalized_query,
        )

        conditions = [
            PurchaseOrder.reference_number
            .ilike(pattern),
            PurchaseOrder.title.ilike(pattern),
            PurchaseOrder.description.ilike(pattern),
        ]

        if supplier_ids:
            conditions.append(
                PurchaseOrder.supplier_id.in_(
                    supplier_ids
                )
            )

        query = query.filter(or_(*conditions))

    orders = (
        query.order_by(
            PurchaseOrder.created_at.desc(),
            PurchaseOrder.id.desc(),
        )
        .limit(limit)
        .all()
    )

    result: list[dict] = []

    for order in orders:
        lines = list(order.lines or [])

        total_in_base = sum(
            (
                Decimal(
                    str(line.ordered_quantity)
                )
                * Decimal(
                    str(line.unit_price_base)
                )
                for line in lines
            ),
            Decimal("0"),
        )
        additional_costs_base = sum(
            (
                Decimal(
                    str(cost.amount_base or 0)
                )
                for cost in order.costs or []
            ),
            Decimal("0"),
        )

        result.append(
            {
                "reference_number": (
                    order.reference_number
                ),
                "title": order.title,
                "supplier_name": (
                    order.supplier_name
                ),
                "status": order.status,
                "approval_status": (
                    order.approval_status
                ),
                "source_rfq_id": (
                    order.source_rfq_id
                ),
                "phase_count": len(
                    order.phases or []
                ),
                "item_count": len(lines),
                "total_in_base": total_in_base,
                "additional_costs_base": (
                    additional_costs_base
                ),
                "grand_total_base": (
                    total_in_base
                    + additional_costs_base
                ),
                "created_at": order.created_at,
            }
        )

    return result

def confirm_purchase_order_cost_actual(
    db: Session,
    user: User,
    po_id: int,
    cost_id: int,
    *,
    amount: Decimal,
    currency_id: int,
) -> PurchaseOrderCost:
    purchase_order = get_po_or_404(
        db=db,
        po_id=po_id,
        user=user,
    )

    cost = _get_purchase_order_cost_or_404(
        db=db,
        purchase_order_id=(
            purchase_order.id
        ),
        cost_id=cost_id,
    )

    paid_base = (
        _get_purchase_order_cost_paid_base(
            db=db,
            user=user,
            cost_id=cost.id,
        )
    )

    current_currency_id = (
        cost.actual_currency_id
        if (
            cost.actual_currency_id
            is not None
        )
        else cost.predicted_currency_id
    )

    if (
        paid_base > 0
        and current_currency_id
        is not None
        and int(currency_id)
        != int(current_currency_id)
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COST_HAS_PAYMENTS,
            (
                "Cost currency cannot be "
                "changed after payment"
            ),
        )

    actual = (
        _prepare_purchase_order_cost_money_bundle(
            db=db,
            purchase_order=purchase_order,
            amount=amount,
            currency_id=currency_id,
        )
    )

    if (
        paid_base > 0
        and Decimal(
            str(actual["amount_base"])
        )
        < paid_base
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COST_ACTUAL_BELOW_PAID,
            (
                "Actual cost cannot be "
                "lower than the paid amount"
            ),
        )

    cost.actual_amount = actual["amount"]
    cost.actual_currency_id = (
        actual["currency_id"]
    )
    cost.actual_amount_base = (
        actual["amount_base"]
    )
    cost.actual_exchange_rate_used = (
        actual["exchange_rate_used"]
    )
    cost.actual_confirmed_at = (
        datetime.utcnow()
    )
    cost.actual_confirmed_by_user_id = (
        user.id
    )

    db.commit()
    db.refresh(cost)

    return cost


def get_purchase_cost_reference_for_finance(
    db: Session,
    current_user: User,
    cost_id: int,
) -> dict:
    company_id = _tenant_id(
        current_user
    )

    cost = (
        db.query(PurchaseOrderCost)
        .join(
            PurchaseOrder,
            PurchaseOrder.id
            == PurchaseOrderCost
            .purchase_order_id,
        )
        .filter(
            PurchaseOrderCost.id
            == cost_id,
            PurchaseOrder.company_id
            == company_id,
        )
        .first()
    )

    if cost is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_COST_NOT_FOUND,
            "Purchase-order cost not found",
        )

    target_is_actual = (
        cost.actual_amount_base
        is not None
    )

    return {
        "cost_id": cost.id,
        "purchase_order_id": (
            cost.purchase_order_id
        ),
        "company_id": company_id,
        "supplier_id": (
            cost.purchase_order
            .supplier_id
        ),
        "cost_type": cost.cost_type,
        "description": cost.description,
        "target_source": (
            "actual"
            if target_is_actual
            else "predicted"
        ),
        "target_amount": (
            cost.actual_amount
            if target_is_actual
            else cost.predicted_amount
        ),
        "target_currency_id": (
            cost.actual_currency_id
            if target_is_actual
            else (
                cost
                .predicted_currency_id
            )
        ),
        "target_amount_base": (
            cost.actual_amount_base
            if target_is_actual
            else (
                cost
                .predicted_amount_base
            )
        ),
        "target_exchange_rate_used": (
            cost.actual_exchange_rate_used
            if target_is_actual
            else (
                cost
                .predicted_exchange_rate_used
            )
        ),
        "base_currency_id": (
            cost.base_currency_id
        ),
        "actual_confirmed": (
            target_is_actual
        ),
    }
