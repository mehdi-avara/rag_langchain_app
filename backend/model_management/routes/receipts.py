from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permissions
from Models import User
from financial_management.routes.receipts import create_receipt, get_receipt, get_receipts_by_ids
from financial_management.schemas import FinancialReceiptBatchRequest, FinancialReceiptSearchRequest
from financial_management.search.routes import search_receipts

from ..models import ModelReceiptLink
from ..schemas import (
    ModelCreateReceiptAndLinkRequest,
    ModelReceiptLinkCreate,
    ModelReceiptLinkOut,
    ModelReceiptOut,
    ModelReceiptSearchRequest,
    ModelReceiptSummaryOut,
)
from ..services import (
    get_model_or_404,
    get_receipt_ids,
    safe_embed_link_note,
    search_model_receipt_link_ids,
)


router = APIRouter()


def _receipt_rows_to_out(
    receipt_ids: list[int],
    links_by_receipt_id: dict[int, ModelReceiptLink],
    db: Session,
    current_user: User,
) -> list[ModelReceiptOut]:
    receipts = get_receipts_by_ids(
        payload=FinancialReceiptBatchRequest(ids=receipt_ids),
        db=db,
        current_user=current_user,
    )
    receipts_by_id = {receipt.id: receipt for receipt in receipts}
    output: list[ModelReceiptOut] = []
    for receipt_id in receipt_ids:
        receipt = receipts_by_id.get(receipt_id)
        link = links_by_receipt_id.get(receipt_id)
        if receipt is None or link is None:
            continue
        output.append(
            ModelReceiptOut(
                receipt=receipt,
                note=link.note,
                linked_at=link.created_at,
            )
        )
    return output


def _build_receipt_summary(items: list[ModelReceiptOut]) -> ModelReceiptSummaryOut:
    total_input = Decimal("0")
    total_output = Decimal("0")
    for item in items:
        if item.receipt.direction == "input":
            total_input += item.receipt.amount
        else:
            total_output += item.receipt.amount
    return ModelReceiptSummaryOut(
        total_receipts=len(items),
        total_input_amount=total_input,
        total_output_amount=total_output,
        total_cost_amount=total_output,
        net_amount=total_input - total_output,
    )


@router.post("/{model_id}/receipts", response_model=ModelReceiptLinkOut, status_code=status.HTTP_201_CREATED)
def link_receipt(
    model_id: int,
    payload: ModelReceiptLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage", "financial_management:receipts:read")),
):
    _ = get_model_or_404(db, model_id, current_user)
    _ = get_receipt(receipt_id=payload.receipt_id, db=db, current_user=current_user)

    link = (
        db.query(ModelReceiptLink)
        .filter(
            ModelReceiptLink.model_id == model_id,
            ModelReceiptLink.receipt_id == payload.receipt_id,
        )
        .first()
    )
    note_embedding = safe_embed_link_note(payload.note)
    if link:
        link.note = payload.note
        link.note_embedding = note_embedding
        db.commit()
        db.refresh(link)
        return link

    link = ModelReceiptLink(
        model_id=model_id,
        receipt_id=payload.receipt_id,
        linked_by_user_id=current_user.id,
        note=payload.note,
        note_embedding=note_embedding,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.post("/{model_id}/receipts/create", response_model=ModelReceiptLinkOut, status_code=status.HTTP_201_CREATED)
def create_receipt_and_link(
    model_id: int,
    body: ModelCreateReceiptAndLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage", "financial_management:receipts:create", "financial_management:receipts:read")),
):
    _ = get_model_or_404(db, model_id, current_user)
    receipt = create_receipt(payload=body.payload, db=db, current_user=current_user)
    payload = ModelReceiptLinkCreate(receipt_id=receipt.id, note=body.link_description)
    return link_receipt(model_id=model_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{model_id}/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_receipt(
    model_id: int,
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage")),
):
    _ = get_model_or_404(db, model_id, current_user)
    _ = get_receipt(receipt_id=receipt_id, db=db, current_user=current_user)
    link = (
        db.query(ModelReceiptLink)
        .filter(
            ModelReceiptLink.model_id == model_id,
            ModelReceiptLink.receipt_id == receipt_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()
    return None


@router.get("/{model_id}/receipts", response_model=List[ModelReceiptOut])
def list_linked_receipts(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage", "financial_management:receipts:read", "financial_management:receipts:search")),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_model_or_404(db, model_id, current_user)
    links = (
        db.query(ModelReceiptLink)
        .filter(ModelReceiptLink.model_id == model_id)
        .order_by(ModelReceiptLink.created_at.desc())
        .all()
    )
    receipt_ids = [link.receipt_id for link in links]
    links_by_receipt_id = {link.receipt_id: link for link in links}
    if not receipt_ids:
        return []

    if search:
        route_hits = search_receipts(
            payload=FinancialReceiptSearchRequest(
                query=search,
                ids=receipt_ids,
                mode="hybrid",
                limit=limit,
            ),
            db=db,
            current_user=current_user,
        )
        route_ids = [hit.receipt_id for hit in route_hits]
        note_ids = search_model_receipt_link_ids(db=db, model_id=model_id, query_text=search, mode="hybrid", limit=limit)
        ordered_ids: list[int] = []
        seen: set[int] = set()
        for receipt_id in route_ids + note_ids:
            if receipt_id in seen:
                continue
            seen.add(receipt_id)
            ordered_ids.append(receipt_id)
        receipt_ids = ordered_ids

    paged_ids = receipt_ids[offset: offset + limit]
    return _receipt_rows_to_out(paged_ids, links_by_receipt_id, db, current_user)


@router.post("/{model_id}/receipts/search", response_model=List[ModelReceiptOut], status_code=status.HTTP_200_OK)
def search_linked_receipts(
    model_id: int,
    payload: ModelReceiptSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage", "financial_management:receipts:search", "financial_management:receipts:read")),
):
    _ = get_model_or_404(db, model_id, current_user)
    links = db.query(ModelReceiptLink).filter(ModelReceiptLink.model_id == model_id).order_by(ModelReceiptLink.created_at.desc()).all()
    receipt_ids = [link.receipt_id for link in links]
    links_by_receipt_id = {link.receipt_id: link for link in links}
    if not receipt_ids:
        return []
    route_hits = search_receipts(
        payload=FinancialReceiptSearchRequest(
            query=payload.query,
            ids=receipt_ids,
            mode=payload.mode,
            limit=payload.limit,
        ),
        db=db,
        current_user=current_user,
    )
    route_ids = [hit.receipt_id for hit in route_hits]
    note_ids = search_model_receipt_link_ids(
        db=db,
        model_id=model_id,
        query_text=payload.query,
        mode=payload.mode,
        limit=payload.limit,
    )
    ordered_ids: list[int] = []
    seen: set[int] = set()
    for receipt_id in route_ids + note_ids:
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        ordered_ids.append(receipt_id)
    return _receipt_rows_to_out(ordered_ids[:payload.limit], links_by_receipt_id, db, current_user)


@router.get("/{model_id}/receipts/summary", response_model=ModelReceiptSummaryOut)
def get_model_receipt_summary(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("models:receipts:manage", "financial_management:receipts:read")),
):
    _ = get_model_or_404(db, model_id, current_user)
    receipt_ids = get_receipt_ids(db, model_id)
    links = db.query(ModelReceiptLink).filter(ModelReceiptLink.model_id == model_id).all()
    links_by_receipt_id = {link.receipt_id: link for link in links}
    items = _receipt_rows_to_out(receipt_ids, links_by_receipt_id, db, current_user)
    return _build_receipt_summary(items)
