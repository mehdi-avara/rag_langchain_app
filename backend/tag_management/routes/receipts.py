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

from ..models import TagReceiptLink
from ..schemas import (
    TagCreateReceiptAndLinkRequest,
    TagReceiptLinkCreate,
    TagReceiptLinkOut,
    TagReceiptOut,
    TagReceiptSearchRequest,
    TagReceiptSummaryOut,
)
from ..services import (
    get_receipt_ids,
    get_tag_or_404,
    safe_embed_link_note,
    search_tag_receipt_link_ids,
)


router = APIRouter()


def _receipt_rows_to_out(
    receipt_ids: list[int],
    links_by_receipt_id: dict[int, TagReceiptLink],
    db: Session,
    current_user: User,
) -> list[TagReceiptOut]:
    receipts = get_receipts_by_ids(
        payload=FinancialReceiptBatchRequest(ids=receipt_ids),
        db=db,
        current_user=current_user,
    )
    receipts_by_id = {receipt.id: receipt for receipt in receipts}
    output: list[TagReceiptOut] = []
    for receipt_id in receipt_ids:
        receipt = receipts_by_id.get(receipt_id)
        link = links_by_receipt_id.get(receipt_id)
        if receipt is None or link is None:
            continue
        output.append(
            TagReceiptOut(
                receipt=receipt,
                note=link.note,
                linked_at=link.created_at,
            )
        )
    return output


def _build_receipt_summary(items: list[TagReceiptOut]) -> TagReceiptSummaryOut:
    total_input = Decimal("0")
    total_output = Decimal("0")
    for item in items:
        if item.receipt.direction == "input":
            total_input += item.receipt.amount
        else:
            total_output += item.receipt.amount
    return TagReceiptSummaryOut(
        total_receipts=len(items),
        total_input_amount=total_input,
        total_output_amount=total_output,
        total_cost_amount=total_output,
        net_amount=total_input - total_output,
    )


@router.post("/{tag_id}/receipts", response_model=TagReceiptLinkOut, status_code=status.HTTP_201_CREATED)
def link_receipt(
    tag_id: int,
    payload: TagReceiptLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts", "financial_management:receipts:read")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    _ = get_receipt(receipt_id=payload.receipt_id, db=db, current_user=current_user)

    link = (
        db.query(TagReceiptLink)
        .filter(
            TagReceiptLink.tag_id == tag_id,
            TagReceiptLink.receipt_id == payload.receipt_id,
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

    link = TagReceiptLink(
        tag_id=tag_id,
        receipt_id=payload.receipt_id,
        linked_by_user_id=current_user.id,
        note=payload.note,
        note_embedding=note_embedding,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.post("/{tag_id}/receipts/create", response_model=TagReceiptLinkOut, status_code=status.HTTP_201_CREATED)
def create_receipt_and_link(
    tag_id: int,
    body: TagCreateReceiptAndLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts", "financial_management:receipts:create", "financial_management:receipts:read")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    receipt = create_receipt(payload=body.payload, db=db, current_user=current_user)
    payload = TagReceiptLinkCreate(receipt_id=receipt.id, note=body.link_description)
    return link_receipt(tag_id=tag_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{tag_id}/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_receipt(
    tag_id: int,
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    _ = get_receipt(receipt_id=receipt_id, db=db, current_user=current_user)
    link = (
        db.query(TagReceiptLink)
        .filter(
            TagReceiptLink.tag_id == tag_id,
            TagReceiptLink.receipt_id == receipt_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()
    return None


@router.get("/{tag_id}/receipts", response_model=List[TagReceiptOut], status_code=status.HTTP_200_OK)
def list_linked_receipts(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts", "financial_management:receipts:read", "financial_management:receipts:search")),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    links = db.query(TagReceiptLink).filter(TagReceiptLink.tag_id == tag_id).order_by(TagReceiptLink.created_at.desc()).all()
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
        note_ids = search_tag_receipt_link_ids(db=db, tag_id=tag_id, query_text=search, mode="hybrid", limit=limit)
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


@router.post("/{tag_id}/receipts/search", response_model=List[TagReceiptOut], status_code=status.HTTP_200_OK)
def search_linked_receipts(
    tag_id: int,
    payload: TagReceiptSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts", "financial_management:receipts:search", "financial_management:receipts:read")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    links = db.query(TagReceiptLink).filter(TagReceiptLink.tag_id == tag_id).order_by(TagReceiptLink.created_at.desc()).all()
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
    note_ids = search_tag_receipt_link_ids(
        db=db,
        tag_id=tag_id,
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


@router.get("/{tag_id}/receipts/summary", response_model=TagReceiptSummaryOut, status_code=status.HTTP_200_OK)
def get_tag_receipt_summary(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions("tags:receipts", "financial_management:receipts:read")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    receipt_ids = get_receipt_ids(db, tag_id)
    links = db.query(TagReceiptLink).filter(TagReceiptLink.tag_id == tag_id).all()
    links_by_receipt_id = {link.receipt_id: link for link in links}
    items = _receipt_rows_to_out(receipt_ids, links_by_receipt_id, db, current_user)
    return _build_receipt_summary(items)
