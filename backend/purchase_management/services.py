"""Business logic for purchase_management.

Cross-module rule: when a phase moves to 'received', dispatch a Celery task
to notify the warehouse. No direct import from warehouse_management.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import User

from .models import (
    CostAllocationMethod,
    PurchaseApprovalStatus,
    PurchaseOrder,
    PurchaseOrderCost,
    PurchaseOrderReceiptLink,
    PurchaseOrderStatus,
    PurchasePhase,
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
    return user.company_id


# ── PurchaseOrder CRUD ────────────────────────────────────────────────────────

def get_po_or_404(db: Session, po_id: int, user: User) -> PurchaseOrder:
    po = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.id == po_id, PurchaseOrder.company_id == _tenant_id(user))
        .first()
    )
    if not po:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return po


def list_purchase_orders(
    db: Session,
    user: User,
    po_status: Optional[str] = None,
    approval_status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> List[PurchaseOrder]:
    q = db.query(PurchaseOrder).filter(PurchaseOrder.company_id == _tenant_id(user))
    if po_status:
        q = q.filter(PurchaseOrder.status == po_status)
    if approval_status:
        q = q.filter(PurchaseOrder.approval_status == approval_status)
    return q.order_by(PurchaseOrder.created_at.desc()).offset((page - 1) * size).limit(size).all()


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


def create_purchase_order(
    db: Session,
    user: User,
    title: Optional[str],
    supplier_id: Optional[int],
    supplier_name: Optional[str],
    currency_id: int,
    base_currency_id: int,
    exchange_rate_used: Decimal,
    description: Optional[str],
) -> PurchaseOrder:
    reference_number = _next_reference_number(db, _tenant_id(user))
    resolved_supplier_id, resolved_supplier_name = _resolve_supplier_for_purchase(
        db=db,
        user=user,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
    )

    po = PurchaseOrder(
        company_id=_tenant_id(user),
        reference_number=reference_number,
        title=title,
        supplier_id=resolved_supplier_id,
        supplier_name=resolved_supplier_name,
        currency_id=currency_id,
        base_currency_id=base_currency_id,
        exchange_rate_used=exchange_rate_used,
        description=description,
        created_by_user_id=user.id,
        status=PurchaseOrderStatus.DRAFT.value,
        approval_status=PurchaseApprovalStatus.DRAFT.value,
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    return po


def update_purchase_order(db: Session, user: User, po_id: int, **kwargs) -> PurchaseOrder:
    po = get_po_or_404(db, po_id, user)

    if po.status == PurchaseOrderStatus.CANCELLED.value:
        raise HTTPException(status_code=422, detail="Cannot edit a cancelled purchase order")

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


def process_approval(db: Session, user: User, po_id: int, action: str, note: Optional[str]) -> PurchaseOrder:
    po = get_po_or_404(db, po_id, user)
    if action == "submit":
        if po.approval_status != PurchaseApprovalStatus.DRAFT.value:
            raise HTTPException(status_code=422, detail="Only draft orders can be submitted for approval")
        po.approval_status = PurchaseApprovalStatus.PENDING.value
    elif action == "approve":
        if po.approval_status != PurchaseApprovalStatus.PENDING.value:
            raise HTTPException(status_code=422, detail="Only pending orders can be approved")
        po.approval_status = PurchaseApprovalStatus.APPROVED.value
        po.approved_by_user_id = user.id
    elif action == "reject":
        if po.approval_status not in (PurchaseApprovalStatus.PENDING.value,):
            raise HTTPException(status_code=422, detail="Only pending orders can be rejected")
        po.approval_status = PurchaseApprovalStatus.REJECTED.value
    else:
        raise HTTPException(status_code=422, detail=f"Unknown approval action: {action}")
    db.commit()
    db.refresh(po)
    return po


# ── PurchasePhase CRUD ────────────────────────────────────────────────────────

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

    new_status = kwargs.get("status")
    for key, value in kwargs.items():
        if value is not None:
            setattr(phase, key, value)
    db.commit()

    # Cross-module event: when a phase is received, notify warehouse via Celery
    if new_status == PurchasePhaseStatus.RECEIVED.value:
        _dispatch_warehouse_receipt_event(phase_id=phase.id)

    db.refresh(phase)
    return phase


def _dispatch_warehouse_receipt_event(phase_id: int) -> None:
    """Dispatch Celery task to notify the warehouse of a received phase.

    The warehouse module's Celery task reads phase items and creates StockMovement records.
    No direct import from warehouse_management — only the task name is referenced.
    """
    try:
        from core.celery.celery_app import celery_app
        celery_app.send_task(
            "warehouse_management.tasks.on_purchase_phase_received",
            args=[phase_id],
        )
    except Exception:
        # Task queue unavailable — log and continue. Warehouse can reconcile manually.
        import logging
        logging.getLogger(__name__).warning(
            "Could not dispatch warehouse receipt event for phase %s", phase_id
        )


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


def add_phase_item(
    db: Session,
    user: User,
    po_id: int,
    phase_id: int,
    item_name: str,
    item_code: Optional[str],
    quantity: Decimal,
    unit: str,
    unit_price: Decimal,
    currency_id: int,
    unit_price_base: Decimal,
    base_currency_id: int,
    exchange_rate_used: Decimal,
    notes: Optional[str],
) -> PurchasePhaseItem:
    phase = _get_phase_or_404(db, user, po_id, phase_id)
    line_total = quantity * unit_price
    line_total_base = quantity * unit_price_base
    item = PurchasePhaseItem(
        phase_id=phase.id,
        item_name=item_name,
        item_code=item_code,
        quantity=quantity,
        unit=unit,
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
    for key, value in kwargs.items():
        if value is not None:
            setattr(item, key, value)
    # Recalculate line totals if qty/price changed
    item.line_total = item.quantity * item.unit_price
    item.line_total_base = item.quantity * item.unit_price_base
    db.commit()
    db.refresh(item)
    return item


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

def get_summary(db: Session, user: User, po_id: int) -> dict:
    po = get_po_or_404(db, po_id, user)
    item_count = 0
    total_in_currency = Decimal("0")
    total_in_base = Decimal("0")

    for phase in po.phases:
        for item in phase.items:
            item_count += 1
            total_in_currency += Decimal(str(item.line_total))
            total_in_base += Decimal(str(item.line_total_base))

    additional_costs_base = sum(
        Decimal(str(c.amount_base)) for c in po.costs
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


# ── Embedding ─────────────────────────────────────────────────────────────────

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
