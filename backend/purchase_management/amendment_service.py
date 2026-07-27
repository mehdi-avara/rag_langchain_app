from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import User
from core.exceptions.error_codes import (
    PURCHASE_ORDER_AMENDMENT_ALREADY_OPEN,
    PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
    PURCHASE_ORDER_AMENDMENT_NOT_ALLOWED,
    PURCHASE_ORDER_AMENDMENT_NOT_EDITABLE,
    PURCHASE_ORDER_AMENDMENT_NOT_FOUND,
    PURCHASE_ORDER_AMENDMENT_POSTED_RECEIPTS_EXIST,
    PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
)

from .models import (
    PurchaseAmendmentStatus,
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderAmendment,
    PurchaseOrderCost,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
)
from .services import (
    _assert_purchase_order_ready_for_submission,
    _tenant_id,
    get_po_or_404,
    purchase_error,
    _synchronize_purchase_order_goods_prediction,
)


ACTIVE_AMENDMENT_STATUSES = {
    PurchaseAmendmentStatus.DRAFT.value,
    PurchaseAmendmentStatus.PENDING.value,
}

BLOCKED_AMENDMENT_ORDER_STATUSES = {
    PurchaseOrderStatus.RECEIVED.value,
    PurchaseOrderStatus.CLOSED.value,
    PurchaseOrderStatus.CANCELLED.value,
}


def _decimal_text(value) -> str:
    return str(
        Decimal(str(value))
    )


def build_purchase_order_commercial_snapshot(
    purchase_order: PurchaseOrder,
) -> dict:
    lines = sorted(
        list(purchase_order.lines or []),
        key=lambda line: (
            line.line_number,
            line.id or 0,
        ),
    )
    costs = sorted(
        list(purchase_order.costs or []),
        key=lambda cost: cost.id or 0,
    )

    return {
        "schema_version": 1,
        "header": {
            "supplier_id": (
                purchase_order.supplier_id
            ),
            "title": purchase_order.title,
            "description": (
                purchase_order.description
            ),
        },
        "approval": {
            "approval_status": (
                purchase_order.approval_status
            ),
            "approved_by_user_id": (
                purchase_order.approved_by_user_id
            ),
            "operational_status": (
                purchase_order.status
            ),
        },
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "item_id": line.item_id,
                "ordered_quantity": (
                    _decimal_text(
                        line.ordered_quantity
                    )
                ),
                "unit_id": line.unit_id,
                "line_description": (
                    line.line_description
                ),
                "unit_price": (
                    _decimal_text(
                        line.unit_price
                    )
                ),
                "currency_id": (
                    line.currency_id
                ),
                "unit_price_base": (
                    _decimal_text(
                        line.unit_price_base
                    )
                ),
                "exchange_rate_used": (
                    _decimal_text(
                        line.exchange_rate_used
                    )
                ),
                "notes": line.notes,
                "allocations": [
                    {
                        "id": allocation.id,
                        "phase_id": (
                            allocation.phase_id
                        ),
                        "allocated_quantity": (
                            _decimal_text(
                                allocation
                                .allocated_quantity
                            )
                        ),
                    }
                    for allocation in sorted(
                        list(
                            line.allocations or []
                        ),
                        key=lambda allocation: (
                            allocation.id or 0
                        ),
                    )
                ],
            }
            for line in lines
        ],
        "costs": [
            {
                "id": cost.id,
                "cost_type": cost.cost_type,
                "description": cost.description,
                "amount": _decimal_text(
                    cost.amount
                ),
                "currency_id": (
                    cost.currency_id
                ),
                "amount_base": (
                    _decimal_text(
                        cost.amount_base
                    )
                ),
                "base_currency_id": (
                    cost.base_currency_id
                ),
                "exchange_rate_used": (
                    _decimal_text(
                        cost.exchange_rate_used
                    )
                ),
                "allocation_method": (
                    cost.allocation_method
                ),
            }
            for cost in costs
        ],
    }


def _commercial_snapshot_body(
    snapshot: dict,
) -> dict:
    return {
        "header": snapshot.get("header"),
        "lines": snapshot.get("lines"),
        "costs": snapshot.get("costs"),
    }


def restore_purchase_order_commercial_snapshot(
    db: Session,
    purchase_order: PurchaseOrder,
    snapshot: dict,
) -> None:
    header = snapshot["header"]
    approval = snapshot["approval"]

    purchase_order.supplier_id = (
        header["supplier_id"]
    )
    purchase_order.title = header["title"]
    purchase_order.description = (
        header["description"]
    )
    purchase_order.status = (
        approval["operational_status"]
    )
    purchase_order.approval_status = (
        approval["approval_status"]
    )
    purchase_order.approved_by_user_id = (
        approval["approved_by_user_id"]
    )

    snapshot_lines = {
        int(item["id"]): item
        for item in snapshot.get("lines", [])
    }

    snapshot_allocations = {}

    for line_snapshot in snapshot_lines.values():
        for allocation_snapshot in (
            line_snapshot.get(
                "allocations",
                [],
            )
        ):
            snapshot_allocations[
                int(allocation_snapshot["id"])
            ] = {
                **allocation_snapshot,
                "purchase_order_line_id": (
                    int(line_snapshot["id"])
                ),
            }

    current_allocations = (
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

    current_allocations_by_id = {
        allocation.id: allocation
        for allocation in current_allocations
    }

    for allocation in current_allocations:
        if (
            allocation.id
            not in snapshot_allocations
            and allocation.purchase_order_line_id
            in snapshot_lines
        ):
            db.delete(allocation)

    db.flush()

    current_lines = (
        db.query(PurchaseOrderLine)
        .filter(
            PurchaseOrderLine.purchase_order_id
            == purchase_order.id
        )
        .all()
    )

    current_lines_by_id = {
        line.id: line
        for line in current_lines
    }

    for line_id, line_snapshot in (
        snapshot_lines.items()
    ):
        line = current_lines_by_id.get(line_id)

        if line is None:
            line = PurchaseOrderLine(
                id=line_id,
                purchase_order_id=(
                    purchase_order.id
                ),
            )
            db.add(line)

        line.line_number = (
            line_snapshot["line_number"]
        )
        line.item_id = line_snapshot["item_id"]
        line.ordered_quantity = Decimal(
            line_snapshot["ordered_quantity"]
        )
        line.unit_id = line_snapshot["unit_id"]
        line.line_description = (
            line_snapshot["line_description"]
        )
        line.unit_price = Decimal(
            line_snapshot["unit_price"]
        )
        line.currency_id = (
            line_snapshot["currency_id"]
        )
        line.unit_price_base = Decimal(
            line_snapshot["unit_price_base"]
        )
        line.exchange_rate_used = Decimal(
            line_snapshot["exchange_rate_used"]
        )
        line.notes = line_snapshot["notes"]

    db.flush()

    for (
        allocation_id,
        allocation_snapshot,
    ) in snapshot_allocations.items():
        allocation = (
            current_allocations_by_id.get(
                allocation_id
            )
        )

        if allocation is None:
            allocation = (
                PurchasePhaseAllocation(
                    id=allocation_id,
                )
            )
            db.add(allocation)

        allocation.phase_id = (
            allocation_snapshot["phase_id"]
        )
        allocation.purchase_order_line_id = (
            allocation_snapshot[
                "purchase_order_line_id"
            ]
        )
        allocation.allocated_quantity = Decimal(
            allocation_snapshot[
                "allocated_quantity"
            ]
        )

    db.flush()

    for line in current_lines:
        if line.id not in snapshot_lines:
            db.delete(line)

    snapshot_costs = {
        int(item["id"]): item
        for item in snapshot.get("costs", [])
    }

    current_costs = (
        db.query(PurchaseOrderCost)
        .filter(
            PurchaseOrderCost.purchase_order_id
            == purchase_order.id
        )
        .all()
    )

    current_costs_by_id = {
        cost.id: cost
        for cost in current_costs
    }

    for cost in current_costs:
        if cost.id not in snapshot_costs:
            db.delete(cost)

    for cost_id, cost_snapshot in (
        snapshot_costs.items()
    ):
        cost = current_costs_by_id.get(cost_id)

        if cost is None:
            cost = PurchaseOrderCost(
                id=cost_id,
                purchase_order_id=(
                    purchase_order.id
                ),
            )
            db.add(cost)

        cost.cost_type = (
            cost_snapshot["cost_type"]
        )
        cost.description = (
            cost_snapshot["description"]
        )
        cost.amount = Decimal(
            cost_snapshot["amount"]
        )
        cost.currency_id = (
            cost_snapshot["currency_id"]
        )
        cost.amount_base = Decimal(
            cost_snapshot["amount_base"]
        )
        cost.base_currency_id = (
            cost_snapshot["base_currency_id"]
        )
        cost.exchange_rate_used = Decimal(
            cost_snapshot[
                "exchange_rate_used"
            ]
        )
        cost.allocation_method = (
            cost_snapshot[
                "allocation_method"
            ]
        )


def get_active_purchase_order_amendment(
    db: Session,
    purchase_order_id: int,
    company_id: int,
    *,
    for_update: bool = False,
) -> Optional[PurchaseOrderAmendment]:
    query = (
        db.query(PurchaseOrderAmendment)
        .filter(
            PurchaseOrderAmendment.company_id
            == company_id,
            PurchaseOrderAmendment.purchase_order_id
            == purchase_order_id,
            PurchaseOrderAmendment.status.in_(
                ACTIVE_AMENDMENT_STATUSES
            ),
        )
        .order_by(
            PurchaseOrderAmendment
            .amendment_number
            .desc()
        )
    )

    if for_update:
        query = query.with_for_update()

    return query.first()


def assert_purchase_order_commercially_editable(
    db: Session,
    purchase_order: PurchaseOrder,
) -> Optional[PurchaseOrderAmendment]:
    if (
        purchase_order.status
        == PurchaseOrderStatus.CANCELLED.value
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
            "Cannot edit a cancelled purchase order",
        )

    if purchase_order.status in {
        PurchaseOrderStatus.CLOSED.value,
        PurchaseOrderStatus.RECEIVED.value,
    }:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
            (
                "Commercial terms cannot be edited "
                "in the current purchase-order status"
            ),
        )

    active_amendment = (
        get_active_purchase_order_amendment(
            db=db,
            purchase_order_id=purchase_order.id,
            company_id=purchase_order.company_id,
        )
    )

    if active_amendment is not None:
        if (
            active_amendment.status
            != PurchaseAmendmentStatus.DRAFT.value
        ):
            purchase_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                PURCHASE_ORDER_AMENDMENT_NOT_EDITABLE,
                (
                    "Commercial terms cannot be edited "
                    "while the amendment is pending"
                ),
            )

        return active_amendment

    if purchase_order.approval_status in {
        PurchaseApprovalStatus.DRAFT.value,
        PurchaseApprovalStatus.REJECTED.value,
    }:
        return None

    purchase_error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE,
        (
            "Approved or pending commercial terms "
            "require an active draft amendment"
        ),
    )


def _purchase_order_has_posted_receipts(
    db: Session,
    purchase_order_id: int,
) -> bool:
    from goods_receipt_management.models import (
        GoodsReceiptItem,
        GoodsReceiptNote,
        GoodsReceiptStatus,
    )

    return (
        db.query(GoodsReceiptItem.id)
        .join(
            GoodsReceiptNote,
            GoodsReceiptNote.id
            == GoodsReceiptItem
            .goods_receipt_note_id,
        )
        .join(
            PurchasePhaseAllocation,
            PurchasePhaseAllocation.id
            == GoodsReceiptItem
            .purchase_phase_allocation_id,
        )
        .join(
            PurchasePhase,
            PurchasePhase.id
            == PurchasePhaseAllocation.phase_id,
        )
        .filter(
            PurchasePhase.purchase_order_id
            == purchase_order_id,
            GoodsReceiptNote.status
            == GoodsReceiptStatus.POSTED.value,
        )
        .first()
        is not None
    )


def _get_amendment_or_404(
    db: Session,
    user: User,
    purchase_order_id: int,
    amendment_id: int,
    *,
    for_update: bool = False,
) -> PurchaseOrderAmendment:
    company_id = _tenant_id(user)

    query = db.query(
        PurchaseOrderAmendment
    ).filter(
        PurchaseOrderAmendment.id
        == amendment_id,
        PurchaseOrderAmendment.company_id
        == company_id,
        PurchaseOrderAmendment.purchase_order_id
        == purchase_order_id,
    )

    if for_update:
        query = query.with_for_update()

    amendment = query.first()

    if amendment is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_AMENDMENT_NOT_FOUND,
            "Purchase-order amendment not found",
        )

    return amendment


def list_purchase_order_amendments(
    db: Session,
    user: User,
    purchase_order_id: int,
) -> list[PurchaseOrderAmendment]:
    get_po_or_404(
        db=db,
        po_id=purchase_order_id,
        user=user,
    )

    return (
        db.query(PurchaseOrderAmendment)
        .filter(
            PurchaseOrderAmendment.company_id
            == _tenant_id(user),
            PurchaseOrderAmendment.purchase_order_id
            == purchase_order_id,
        )
        .order_by(
            PurchaseOrderAmendment
            .amendment_number
            .desc()
        )
        .all()
    )


def get_purchase_order_amendment(
    db: Session,
    user: User,
    purchase_order_id: int,
    amendment_id: int,
) -> PurchaseOrderAmendment:
    return _get_amendment_or_404(
        db=db,
        user=user,
        purchase_order_id=purchase_order_id,
        amendment_id=amendment_id,
    )


def open_purchase_order_amendment(
    db: Session,
    user: User,
    purchase_order_id: int,
    reason: str,
) -> PurchaseOrderAmendment:
    normalized_reason = (
        (reason or "").strip()
    )

    if not normalized_reason:
        from core.exceptions.error_codes import (
            PURCHASE_ORDER_AMENDMENT_REASON_REQUIRED,
        )

        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_REASON_REQUIRED,
            "Amendment reason is required",
        )

    company_id = _tenant_id(user)

    purchase_order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.id
            == purchase_order_id,
            PurchaseOrder.company_id
            == company_id,
        )
        .with_for_update(of=PurchaseOrder)
        .first()
    )

    if purchase_order is None:
        purchase_error(
            status.HTTP_404_NOT_FOUND,
            PURCHASE_ORDER_AMENDMENT_NOT_FOUND,
            "Purchase order not found",
        )

    if (
        purchase_order.approval_status
        != PurchaseApprovalStatus.APPROVED.value
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_NOT_ALLOWED,
            (
                "Only an approved purchase order "
                "can enter amendment"
            ),
        )

    if (
        purchase_order.status
        in BLOCKED_AMENDMENT_ORDER_STATUSES
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_NOT_ALLOWED,
            (
                "The purchase order cannot be amended "
                "in its current status"
            ),
        )

    existing = (
        get_active_purchase_order_amendment(
            db=db,
            purchase_order_id=(
                purchase_order.id
            ),
            company_id=company_id,
            for_update=True,
        )
    )

    if existing is not None:
        purchase_error(
            status.HTTP_409_CONFLICT,
            PURCHASE_ORDER_AMENDMENT_ALREADY_OPEN,
            (
                "The purchase order already has "
                "an active amendment"
            ),
        )

    if _purchase_order_has_posted_receipts(
        db=db,
        purchase_order_id=purchase_order.id,
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            (
                PURCHASE_ORDER_AMENDMENT_POSTED_RECEIPTS_EXIST
            ),
            (
                "Commercial amendments are blocked "
                "after a posted goods receipt"
            ),
        )

    next_number = (
        db.query(
            func.coalesce(
                func.max(
                    PurchaseOrderAmendment
                    .amendment_number
                ),
                0,
            )
        )
        .filter(
            PurchaseOrderAmendment.company_id
            == company_id,
            PurchaseOrderAmendment.purchase_order_id
            == purchase_order.id,
        )
        .scalar()
        + 1
    )

    amendment = PurchaseOrderAmendment(
        company_id=company_id,
        purchase_order_id=purchase_order.id,
        amendment_number=next_number,
        status=(
            PurchaseAmendmentStatus.DRAFT.value
        ),
        reason=normalized_reason,
        before_snapshot=(
            build_purchase_order_commercial_snapshot(
                purchase_order
            )
        ),
        created_by_user_id=user.id,
    )

    purchase_order.approval_status = (
        PurchaseApprovalStatus.DRAFT.value
    )
    purchase_order.approved_by_user_id = None

    db.add(amendment)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()

        purchase_error(
            status.HTTP_409_CONFLICT,
            PURCHASE_ORDER_AMENDMENT_ALREADY_OPEN,
            (
                "The purchase order already has "
                "an active amendment"
            ),
        )

        raise exc

    db.refresh(amendment)

    return amendment


def submit_purchase_order_amendment(
    db: Session,
    user: User,
    purchase_order_id: int,
    amendment_id: int,
    note: Optional[str],
) -> PurchaseOrderAmendment:
    amendment = _get_amendment_or_404(
        db=db,
        user=user,
        purchase_order_id=purchase_order_id,
        amendment_id=amendment_id,
        for_update=True,
    )

    if (
        amendment.status
        != PurchaseAmendmentStatus.DRAFT.value
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
            (
                "Only a draft amendment "
                "can be submitted"
            ),
        )

    purchase_order = get_po_or_404(
        db=db,
        po_id=purchase_order_id,
        user=user,
    )

    proposed_snapshot = (
        build_purchase_order_commercial_snapshot(
            purchase_order
        )
    )

    if (
        _commercial_snapshot_body(
            proposed_snapshot
        )
        == _commercial_snapshot_body(
            amendment.before_snapshot
        )
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_NOT_EDITABLE,
            (
                "The amendment contains no "
                "commercial changes"
            ),
        )

    _assert_purchase_order_ready_for_submission(
        purchase_order
    )

    amendment.proposed_snapshot = (
        proposed_snapshot
    )
    amendment.submission_note = (
        (note or "").strip() or None
    )
    amendment.status = (
        PurchaseAmendmentStatus.PENDING.value
    )
    amendment.submitted_by_user_id = user.id
    amendment.submitted_at = datetime.utcnow()
    amendment.updated_at = datetime.utcnow()

    purchase_order.approval_status = (
        PurchaseApprovalStatus.PENDING.value
    )

    db.commit()
    db.refresh(amendment)

    return amendment


def decide_purchase_order_amendment(
    db: Session,
    user: User,
    purchase_order_id: int,
    amendment_id: int,
    action: str,
    note: Optional[str],
) -> PurchaseOrderAmendment:
    amendment = _get_amendment_or_404(
        db=db,
        user=user,
        purchase_order_id=purchase_order_id,
        amendment_id=amendment_id,
        for_update=True,
    )

    if (
        amendment.status
        != PurchaseAmendmentStatus.PENDING.value
    ):
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
            (
                "Only a pending amendment "
                "can be approved or rejected"
            ),
        )

    purchase_order = get_po_or_404(
        db=db,
        po_id=purchase_order_id,
        user=user,
    )

    if action == "approve":
        _synchronize_purchase_order_goods_prediction(
            db=db,
            user=user,
            purchase_order=purchase_order,
        )

        amendment.status = (
            PurchaseAmendmentStatus.APPROVED.value
        )
        purchase_order.approval_status = (
            PurchaseApprovalStatus.APPROVED.value
        )
        purchase_order.approved_by_user_id = (
            user.id
        )

    elif action == "reject":
        restore_purchase_order_commercial_snapshot(
            db=db,
            purchase_order=purchase_order,
            snapshot=amendment.before_snapshot,
        )
        amendment.status = (
            PurchaseAmendmentStatus.REJECTED.value
        )

    else:
        purchase_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION,
            "Unknown amendment decision",
        )

    amendment.decision_note = (
        (note or "").strip() or None
    )
    amendment.decided_by_user_id = user.id
    amendment.decided_at = datetime.utcnow()
    amendment.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(amendment)

    return amendment
