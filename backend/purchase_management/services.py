"""Business logic for purchase_management."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from core.exceptions.error_codes import (
    PURCHASE_ORDER_BASE_CURRENCY_NOT_CONFIGURED,
    PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
    PURCHASE_ORDER_COMMERCIAL_TERMS_MISMATCH,
    PURCHASE_ORDER_CURRENCY_INVALID,
    PURCHASE_ORDER_INVALID_STRUCTURE,
    PURCHASE_ORDER_LINES_REQUIRED,
    PURCHASE_ORDER_NOT_RECEIVABLE,
    PURCHASE_ORDER_REFERENCE_GENERATION_FAILED,
    PURCHASE_ORDER_RFQ_ALREADY_LINKED,
    PURCHASE_ORDER_RFQ_INVALID_WINNER,
    PURCHASE_ORDER_SUPPLIER_REQUIRED,
    PURCHASE_PHASE_ITEM_NOT_FOUND,
    PURCHASE_PHASE_ITEM_OVER_RECEIPT,
    PURCHASE_PHASE_NOT_RECEIVABLE,
    USER_HAS_NO_COMPANY,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from Models import User

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
    PurchasePhaseItem,
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": USER_HAS_NO_COMPANY,
                "message": "Current user does not belong to a company",
            },
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
            PurchaseOrder.rfq_id == rfq_id,
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
        selectinload(PurchaseOrder.lines).selectinload(
            PurchaseOrderLine.allocations
        ),
        selectinload(PurchaseOrder.phases).selectinload(
            PurchasePhase.allocations
        ),
        selectinload(PurchaseOrder.phases).selectinload(
            PurchasePhase.items
        ),
        selectinload(PurchaseOrder.costs),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase order not found",
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
    supplier_id: Optional[int],
    supplier_name: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    if supplier_id is None:
        return None, supplier_name

    from supplier_management.services import get_supplier_or_404

    supplier = get_supplier_or_404(
        db=db,
        supplier_id=supplier_id,
        current_user=user,
    )

    return supplier.id, supplier.name


PRICE_QUANTUM = Decimal("0.0000000001")
RATE_QUANTUM = Decimal("0.0000000001")


def _quantize_decimal(value, decimal_places: int) -> Decimal:
    quantum = Decimal("1").scaleb(-decimal_places)
    return Decimal(str(value)).quantize(
        quantum,
        rounding=ROUND_HALF_UP,
    )


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
        exchange_rate = Decimal(
            str(line["exchange_rate_used"])
        ).quantize(
            RATE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        unit_price = _quantize_decimal(
            line["unit_price"],
            currency.decimal_places,
        )
        unit_price_base = _quantize_decimal(
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
            supplier_name=None,
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
    first_line = prepared_lines[0]

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
                rfq_id=None,
                source_material_requisition_id=None,
                winning_quotation_response_id=None,
                supplier_id=resolved_supplier_id,
                supplier_name=resolved_supplier_name,
                currency_id=first_line["currency_id"],
                base_currency_id=base_currency.id,
                exchange_rate_used=first_line[
                    "exchange_rate_used"
                ],
                description=(
                    (data.get("description") or "").strip()
                    or None
                ),
                created_by_user_id=user.id,
                status=PurchaseOrderStatus.DRAFT.value,
                approval_status=PurchaseApprovalStatus.DRAFT.value,
            )
            db.add(purchase_order)
            db.flush()

            phase = PurchasePhase(
                purchase_order_id=purchase_order.id,
                phase_number=1,
                title="Phase 1",
                description="Initial delivery phase",
                status=PurchasePhaseStatus.DRAFT.value,
                currency_id=first_line["currency_id"],
                exchange_rate_used=first_line[
                    "exchange_rate_used"
                ],
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": PURCHASE_ORDER_RFQ_ALREADY_LINKED,
                "message": "A purchase order already exists for this RFQ",
            },
        )

    source = _get_winning_quotation_reference_for_purchase(
        db=db,
        user=user,
        rfq_id=rfq_id,
    )

    for _ in range(5):
        try:
            reference_number = _next_reference_number(
                db=db,
                company_id=_tenant_id(user),
            )

            description_parts = [
                f"Created from RFQ {source['rfq_number']}.",
                (source.get("description") or "").strip(),
            ]
            description = " ".join(
                part for part in description_parts if part
            )

            purchase_order = PurchaseOrder(
                company_id=_tenant_id(user),
                reference_number=reference_number,
                title=source["title"],
                rfq_id=source["rfq_id"],
                winning_quotation_response_id=source[
                    "winning_quotation_response_id"
                ],
                supplier_id=source["supplier_id"],
                supplier_name=source["supplier_name"],
                currency_id=source["currency_id"],
                base_currency_id=source["base_currency_id"],
                exchange_rate_used=source["exchange_rate_used"],
                description=description,
                created_by_user_id=user.id,
                status=PurchaseOrderStatus.DRAFT.value,
                approval_status=PurchaseApprovalStatus.DRAFT.value,
            )
            db.add(purchase_order)
            db.flush()

            delivery_days = source.get("delivery_days")
            expected_delivery_date = (
                datetime.utcnow() + timedelta(days=delivery_days)
                if delivery_days is not None
                else None
            )

            purchase_phase = PurchasePhase(
                purchase_order_id=purchase_order.id,
                phase_number=1,
                title=f"RFQ {source['rfq_number']} delivery",
                description="Generated from the selected quotation response",
                status=PurchasePhaseStatus.DRAFT.value,
                currency_id=source["currency_id"],
                exchange_rate_used=source["exchange_rate_used"],
                expected_delivery_date=expected_delivery_date,
            )
            db.add(purchase_phase)
            db.flush()

            for source_item in source["items"]:
                if source_item["item_id"] is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": PURCHASE_ORDER_RFQ_INVALID_WINNER,
                            "message": "Winning quotation contains an item without a material reference",
                        },
                    )

                quantity = Decimal(str(source_item["quantity"]))
                unit_price = Decimal(str(source_item["unit_price"]))
                unit_price_base = Decimal(
                    str(source_item["unit_price_base"])
                )

                db.add(
                    PurchasePhaseItem(
                        phase_id=purchase_phase.id,
                        item_id=source_item["item_id"],
                        item_name=source_item["item_name"],
                        item_code=source_item["item_code"],
                        quantity=quantity,
                        unit=source_item["unit_code"],
                        unit_price=unit_price,
                        currency_id=source_item["currency_id"],
                        unit_price_base=unit_price_base,
                        base_currency_id=source_item["base_currency_id"],
                        exchange_rate_used=source_item[
                            "exchange_rate_used"
                        ],
                        line_total=quantity * unit_price,
                        line_total_base=quantity * unit_price_base,
                        notes=source_item.get("notes"),
                    )
                )

            if source.get("mr_id") is not None:
                _mark_requisition_ordered_from_purchase_order(
                    db=db,
                    user=user,
                    requisition_id=source["mr_id"],
                    purchase_order_reference=reference_number,
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

            if "uq_purchase_orders_company_rfq" in detail:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": PURCHASE_ORDER_RFQ_ALREADY_LINKED,
                        "message": "A purchase order already exists for this RFQ",
                    },
                ) from exc

            if "uq_po_company_reference" in detail:
                continue

            raise

        except Exception:
            db.rollback()
            raise

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": PURCHASE_ORDER_RFQ_INVALID_WINNER,
            "message": "Could not generate a unique purchase order reference",
        },
    )


def update_purchase_order(db: Session, user: User, po_id: int, **kwargs) -> PurchaseOrder:
    po = get_po_or_404(db, po_id, user)

    if po.status == PurchaseOrderStatus.CANCELLED.value:
        raise HTTPException(status_code=422, detail="Cannot edit a cancelled purchase order")

    if (
        list(getattr(po, "lines", []) or [])
        and any(
            field in kwargs
            for field in (
                "currency_id",
                "base_currency_id",
                "exchange_rate_used",
            )
        )
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
            "Commercial header fields are derived from normalized purchase-order lines",
        )

    missing = object()
    supplied_supplier_id = kwargs.pop("supplier_id", missing)
    supplied_supplier_name = kwargs.pop("supplier_name", missing)

    if supplied_supplier_id is not missing:
        if supplied_supplier_id is None:
            po.supplier_id = None
            po.supplier_name = (
                supplied_supplier_name
                if supplied_supplier_name is not missing
                else None
            )
        else:
            resolved_supplier_id, resolved_supplier_name = _resolve_supplier_for_purchase(
                db=db,
                user=user,
                supplier_id=supplied_supplier_id,
                supplier_name=None,
            )
            po.supplier_id = resolved_supplier_id
            po.supplier_name = resolved_supplier_name
    elif supplied_supplier_name is not missing:
        po.supplier_name = supplied_supplier_name

    for key, value in kwargs.items():
        if value is not None:
            setattr(po, key, value)

    db.commit()
    db.refresh(po)
    return po

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

    first_line = lines[0]

    if (
        purchase_order.currency_id != first_line.currency_id
        or Decimal(str(purchase_order.exchange_rate_used))
        != Decimal(str(first_line.exchange_rate_used))
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_INVALID_STRUCTURE,
            "Purchase-order header terms do not match its normalized lines",
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
    po = get_po_or_404(db, po_id, user)

    if action == "submit":
        if (
            po.approval_status
            != PurchaseApprovalStatus.DRAFT.value
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Only draft orders can be submitted "
                    "for approval"
                ),
            )

        _assert_purchase_order_ready_for_submission(po)
        po.approval_status = (
            PurchaseApprovalStatus.PENDING.value
        )

    elif action == "approve":
        if (
            po.approval_status
            != PurchaseApprovalStatus.PENDING.value
        ):
            raise HTTPException(
                status_code=422,
                detail="Only pending orders can be approved",
            )

        po.approval_status = (
            PurchaseApprovalStatus.APPROVED.value
        )
        po.status = PurchaseOrderStatus.ORDERED.value
        po.approved_by_user_id = user.id

        for phase in po.phases:
            if phase.status == PurchasePhaseStatus.DRAFT.value:
                phase.status = PurchasePhaseStatus.ORDERED.value

    elif action == "reject":
        if (
            po.approval_status
            != PurchaseApprovalStatus.PENDING.value
        ):
            raise HTTPException(
                status_code=422,
                detail="Only pending orders can be rejected",
            )

        po.approval_status = PurchaseApprovalStatus.REJECTED.value

    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown approval action: {action}",
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
        raise HTTPException(status_code=404, detail="Phase not found")

    for key, value in kwargs.items():
        if value is not None:
            setattr(phase, key, value)

    db.commit()
    db.refresh(phase)
    return phase


# ── PurchasePhaseItem CRUD ────────────────────────────────────────────────────

def _get_phase_or_404(db: Session, user: User, po_id: int, phase_id: int) -> PurchasePhase:
    po = get_po_or_404(db, po_id, user)
    phase = db.query(PurchasePhase).filter(
        PurchasePhase.id == phase_id,
        PurchasePhase.purchase_order_id == po.id,
    ).first()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    return phase


def _resolve_item_for_purchase(
    db: Session,
    user: User,
    item_id: Optional[int],
    item_name: Optional[str],
    item_code: Optional[str],
    unit: Optional[str],
) -> tuple[Optional[int], str, Optional[str], str]:
    if item_id is None:
        normalized_name = (item_name or "").strip()
        if not normalized_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="item_id or item_name is required",
            )
        return None, normalized_name, item_code, (unit or "pcs").strip() or "pcs"

    from material_management.services import get_item_reference

    reference = get_item_reference(
        db=db,
        current_user=user,
        item_id=item_id,
    )

    return (
        reference["id"],
        reference["name"],
        reference["item_code"],
        reference["unit_code"],
    )


def add_phase_item(
    db: Session,
    user: User,
    po_id: int,
    phase_id: int,
    item_id: Optional[int],
    item_name: Optional[str],
    item_code: Optional[str],
    quantity: Decimal,
    unit: Optional[str],
    unit_price: Decimal,
    currency_id: int,
    unit_price_base: Decimal,
    base_currency_id: int,
    exchange_rate_used: Decimal,
    notes: Optional[str],
) -> PurchasePhaseItem:
    phase = _get_phase_or_404(db, user, po_id, phase_id)

    resolved_item_id, resolved_item_name, resolved_item_code, resolved_unit = (
        _resolve_item_for_purchase(
            db=db,
            user=user,
            item_id=item_id,
            item_name=item_name,
            item_code=item_code,
            unit=unit,
        )
    )

    line_total = quantity * unit_price
    line_total_base = quantity * unit_price_base

    item = PurchasePhaseItem(
        phase_id=phase.id,
        item_id=resolved_item_id,
        item_name=resolved_item_name,
        item_code=resolved_item_code,
        quantity=quantity,
        unit=resolved_unit,
        unit_price=unit_price,
        currency_id=currency_id,
        unit_price_base=unit_price_base,
        base_currency_id=base_currency_id,
        exchange_rate_used=exchange_rate_used,
        line_total=line_total,
        line_total_base=line_total_base,
        notes=notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_phase_item(
    db: Session,
    user: User,
    po_id: int,
    phase_id: int,
    item_id: int,
    **kwargs,
) -> PurchasePhaseItem:
    phase = _get_phase_or_404(db, user, po_id, phase_id)
    item = db.query(PurchasePhaseItem).filter(
        PurchasePhaseItem.id == item_id,
        PurchasePhaseItem.phase_id == phase.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    missing = object()
    supplied_item_id = kwargs.pop("item_id", missing)

    if supplied_item_id is not missing:
        if supplied_item_id is None:
            item.item_id = None
        else:
            resolved_item_id, resolved_item_name, resolved_item_code, resolved_unit = (
                _resolve_item_for_purchase(
                    db=db,
                    user=user,
                    item_id=supplied_item_id,
                    item_name=None,
                    item_code=None,
                    unit=None,
                )
            )
            item.item_id = resolved_item_id
            item.item_name = resolved_item_name
            item.item_code = resolved_item_code
            item.unit = resolved_unit

    for key, value in kwargs.items():
        if value is not None:
            setattr(item, key, value)

    item.line_total = item.quantity * item.unit_price
    item.line_total_base = item.quantity * item.unit_price_base

    db.commit()
    db.refresh(item)
    return item


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase phase not found",
        )

    purchase_order, purchase_phase = row

    return {
        "purchase_order_id": purchase_order.id,
        "purchase_phase_id": purchase_phase.id,
    }


def get_phase_item_reference_for_goods_receipt(
    db: Session,
    current_user: User,
    purchase_order_id: int,
    purchase_phase_id: int,
    purchase_phase_item_id: int,
) -> dict:
    phase = _get_phase_or_404(
        db=db,
        user=current_user,
        po_id=purchase_order_id,
        phase_id=purchase_phase_id,
    )

    phase_item = (
        db.query(PurchasePhaseItem)
        .filter(
            PurchasePhaseItem.id == purchase_phase_item_id,
            PurchasePhaseItem.phase_id == phase.id,
        )
        .first()
    )

    if phase_item is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_ITEM_NOT_FOUND,
            "Purchase phase item not found",
        )

    return {
        "id": phase_item.id,
        "item_id": phase_item.item_id,
        "item_code": phase_item.item_code,
        "item_name": phase_item.item_name,
        "unit_code": phase_item.unit,
        "quantity": phase_item.quantity,
        "received_quantity": phase_item.received_quantity,
        "unit_price": phase_item.unit_price,
        "currency_id": phase_item.currency_id,
        "unit_price_base": phase_item.unit_price_base,
        "base_currency_id": phase_item.base_currency_id,
        "exchange_rate_used": phase_item.exchange_rate_used,
    }


def apply_goods_receipt(
    db: Session,
    current_user: User,
    purchase_order_id: int,
    purchase_phase_id: int,
    receipt_date: date,
    receipt_items: list[dict],
) -> None:
    purchase_order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.company_id == _tenant_id(current_user),
        )
        .with_for_update()
        .first()
    )

    if purchase_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase order not found",
        )

    if purchase_order.status in {
        PurchaseOrderStatus.DRAFT.value,
        PurchaseOrderStatus.CANCELLED.value,
        PurchaseOrderStatus.CLOSED.value,
    }:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_NOT_RECEIVABLE,
            "Purchase order cannot receive goods in its current status",
        )

    phase = (
        db.query(PurchasePhase)
        .filter(
            PurchasePhase.id == purchase_phase_id,
            PurchasePhase.purchase_order_id == purchase_order.id,
        )
        .with_for_update()
        .first()
    )

    if phase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase phase not found",
        )

    if phase.status in {
        PurchasePhaseStatus.DRAFT.value,
        PurchasePhaseStatus.CLOSED.value,
    }:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_PHASE_NOT_RECEIVABLE,
            "Purchase phase cannot receive goods in its current status",
        )

    phase_item_ids = [
        receipt_item["purchase_phase_item_id"]
        for receipt_item in receipt_items
    ]

    phase_items = (
        db.query(PurchasePhaseItem)
        .filter(
            PurchasePhaseItem.phase_id == phase.id,
            PurchasePhaseItem.id.in_(phase_item_ids),
        )
        .with_for_update()
        .all()
    )

    phase_items_by_id = {
        phase_item.id: phase_item
        for phase_item in phase_items
    }

    if len(phase_items_by_id) != len(set(phase_item_ids)):
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_PHASE_ITEM_NOT_FOUND,
            "One or more purchase phase items were not found",
        )

    for receipt_item in receipt_items:
        phase_item = phase_items_by_id[
            receipt_item["purchase_phase_item_id"]
        ]
        accepted_quantity = Decimal(str(receipt_item["accepted_quantity"]))
        new_received_quantity = (
            Decimal(str(phase_item.received_quantity))
            + accepted_quantity
        )

        if new_received_quantity > Decimal(str(phase_item.quantity)):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_PHASE_ITEM_OVER_RECEIPT,
                "Accepted quantity exceeds the remaining purchase phase quantity",
            )

    for receipt_item in receipt_items:
        phase_item = phase_items_by_id[
            receipt_item["purchase_phase_item_id"]
        ]
        phase_item.received_quantity = (
            Decimal(str(phase_item.received_quantity))
            + Decimal(str(receipt_item["accepted_quantity"]))
        )

    all_phase_items = (
        db.query(PurchasePhaseItem)
        .filter(PurchasePhaseItem.phase_id == phase.id)
        .all()
    )

    if all_phase_items and all(
        Decimal(str(item.received_quantity))
        >= Decimal(str(item.quantity))
        for item in all_phase_items
    ):
        phase.status = PurchasePhaseStatus.RECEIVED.value
        phase.actual_delivery_date = datetime.combine(
            receipt_date,
            datetime.min.time(),
        )
    elif any(
        Decimal(str(item.received_quantity)) > 0
        for item in all_phase_items
    ) and phase.status == PurchasePhaseStatus.ORDERED.value:
        phase.status = PurchasePhaseStatus.SHIPPED.value

    all_purchase_items = (
        db.query(PurchasePhaseItem)
        .join(
            PurchasePhase,
            PurchasePhaseItem.phase_id == PurchasePhase.id,
        )
        .filter(PurchasePhase.purchase_order_id == purchase_order.id)
        .all()
    )

    if all_purchase_items and all(
        Decimal(str(item.received_quantity))
        >= Decimal(str(item.quantity))
        for item in all_purchase_items
    ):
        purchase_order.status = PurchaseOrderStatus.RECEIVED.value
    elif any(
        Decimal(str(item.received_quantity)) > 0
        for item in all_purchase_items
    ):
        purchase_order.status = PurchaseOrderStatus.PARTIALLY_RECEIVED.value


# ── PurchaseOrderCost ─────────────────────────────────────────────────────────

def add_cost(
    db: Session,
    user: User,
    po_id: int,
    cost_type: str,
    description: Optional[str],
    amount: Decimal,
    currency_id: int,
    amount_base: Decimal,
    base_currency_id: int,
    exchange_rate_used: Decimal,
    allocation_method: str,
) -> PurchaseOrderCost:
    po = get_po_or_404(db, po_id, user)
    cost = PurchaseOrderCost(
        purchase_order_id=po.id,
        cost_type=cost_type,
        description=description,
        amount=amount,
        currency_id=currency_id,
        amount_base=amount_base,
        base_currency_id=base_currency_id,
        exchange_rate_used=exchange_rate_used,
        allocation_method=allocation_method,
    )
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


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

def get_summary(
    db: Session,
    user: User,
    po_id: int,
) -> dict:
    po = get_po_or_404(db, po_id, user)
    normalized_lines = list(po.lines or [])

    if normalized_lines:
        item_count = len(normalized_lines)
        total_in_currency = sum(
            (
                Decimal(str(line.ordered_quantity))
                * Decimal(str(line.unit_price))
                for line in normalized_lines
            ),
            Decimal("0"),
        )
        total_in_base = sum(
            (
                Decimal(str(line.ordered_quantity))
                * Decimal(str(line.unit_price_base))
                for line in normalized_lines
            ),
            Decimal("0"),
        )
    else:
        legacy_items = [
            item
            for phase in po.phases
            for item in phase.items
        ]
        item_count = len(legacy_items)
        total_in_currency = sum(
            (
                Decimal(str(item.line_total))
                for item in legacy_items
            ),
            Decimal("0"),
        )
        total_in_base = sum(
            (
                Decimal(str(item.line_total_base))
                for item in legacy_items
            ),
            Decimal("0"),
        )

    additional_costs_base = sum(
        (
            Decimal(str(cost.amount_base))
            for cost in po.costs
        ),
        Decimal("0"),
    )

    return {
        "purchase_order_id": po.id,
        "reference_number": po.reference_number,
        "phase_count": len(po.phases),
        "item_count": item_count,
        "total_in_currency": total_in_currency,
        "total_in_base": total_in_base,
        "currency_id": po.currency_id,
        "base_currency_id": po.base_currency_id,
        "additional_costs_base": additional_costs_base,
        "grand_total_base": total_in_base + additional_costs_base,
    }


# ── Embedding# ── Embedding ─────────────────────────────────────────────────────────────────

def ensure_po_embeddings(db: Session, user: User, po_ids: Optional[List[int]] = None) -> None:
    """Generate missing description embeddings for PurchaseOrders."""
    try:
        from components.embedding import JinaAPIEmbeddings
        client = JinaAPIEmbeddings()

        q = db.query(PurchaseOrder).filter(
            PurchaseOrder.company_id == _tenant_id(user),
            PurchaseOrder.description_embedding == None,
            PurchaseOrder.description != None,
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


def export_purchase_order_rows(
    db: Session,
    current_user: User,
    query_text: Optional[str] = None,
    po_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    limit: int = 10000,
) -> list[dict]:
    from decimal import Decimal

    from sqlalchemy import or_
    from sqlalchemy.orm import selectinload

    query = (
        db.query(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.lines),
            selectinload(PurchaseOrder.phases).selectinload(
                PurchasePhase.items
            ),
            selectinload(PurchaseOrder.costs),
        )
        .filter(PurchaseOrder.company_id == _tenant_id(current_user))
    )

    if po_status:
        query = query.filter(PurchaseOrder.status == po_status)

    if approval_status:
        query = query.filter(
            PurchaseOrder.approval_status == approval_status
        )

    if query_text:
        pattern = f"%{query_text.strip()}%"
        query = query.filter(
            or_(
                PurchaseOrder.reference_number.ilike(pattern),
                PurchaseOrder.title.ilike(pattern),
                PurchaseOrder.supplier_name.ilike(pattern),
                PurchaseOrder.description.ilike(pattern),
            )
        )

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
        normalized_lines = list(order.lines or [])
        phase_items = [
            item
            for phase in order.phases or []
            for item in phase.items or []
        ]

        if normalized_lines:
            item_count = len(normalized_lines)
            total_in_base = sum(
                (
                    Decimal(str(line.ordered_quantity))
                    * Decimal(str(line.unit_price_base))
                    for line in normalized_lines
                ),
                Decimal("0"),
            )
        else:
            item_count = len(phase_items)
            total_in_base = sum(
                (
                    Decimal(str(item.line_total_base or 0))
                    for item in phase_items
                ),
                Decimal("0"),
            )
        additional_costs_base = sum(
            (
                Decimal(str(cost.amount_base or 0))
                for cost in order.costs or []
            ),
            Decimal("0"),
        )

        result.append(
            {
                "reference_number": order.reference_number,
                "title": order.title,
                "supplier_name": order.supplier_name,
                "status": order.status,
                "approval_status": order.approval_status,
                "rfq_id": order.rfq_id,
                "phase_count": len(order.phases or []),
                "item_count": item_count,
                "total_in_base": total_in_base,
                "additional_costs_base": additional_costs_base,
                "grand_total_base": (
                    total_in_base + additional_costs_base
                ),
                "created_at": order.created_at,
            }
        )

    return result
