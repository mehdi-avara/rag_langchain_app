from __future__ import annotations

from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from Models import User

from ..models import FinancialReceipt
from ..schemas import FinancialReceiptSemanticHit
from ..services import (
    ensure_receipt_embeddings,
    get_receipt_or_404,
    gregorian_to_solar,
    mask_card_number,
    owner_filter_id,
    receipt_to_out,
)
from .repository import (
    search_financial_receipt_hits_semantic,
    search_financial_receipts_text,
)


def build_text_hit(receipt: FinancialReceipt, match_source: str = "text") -> FinancialReceiptSemanticHit:
    return FinancialReceiptSemanticHit(
        receipt_id=receipt.id,
        description=receipt.description,
        tracking_number=receipt.tracking_number,
        amount=Decimal(str(receipt.amount)),
        direction=receipt.direction,
        counterparty_name=receipt.counterparty_name,
        receipt_date=gregorian_to_solar(receipt.receipt_date),
        receipt_date_gregorian=receipt.receipt_date.isoformat(),
        card_id=receipt.credit_card.id,
        card_title=receipt.credit_card.title,
        card_masked_number=mask_card_number(receipt.credit_card.card_number),
        owner_id=receipt.owner_id,
        createdAt=receipt.created_at,
        match_source=match_source,
    )


def build_semantic_hit(row: dict, match_source: str = "semantic") -> FinancialReceiptSemanticHit:
    receipt_date = row["receipt_date"]
    return FinancialReceiptSemanticHit(
        receipt_id=row["receipt_id"],
        description=row["description"],
        tracking_number=row.get("tracking_number"),
        amount=Decimal(str(row["amount"])),
        direction=row["direction"],
        counterparty_name=row["counterparty_name"],
        receipt_date=gregorian_to_solar(receipt_date),
        receipt_date_gregorian=receipt_date.isoformat(),
        card_id=row["credit_card_id"],
        card_title=row["card_title"],
        card_masked_number=mask_card_number(row["card_number"]),
        owner_id=row["owner_id"],
        createdAt=row["createdAt"],
        match_source=match_source,
    )


def merge_receipt_hits(
    primary_hits: Iterable[FinancialReceiptSemanticHit],
    secondary_hits: Iterable[FinancialReceiptSemanticHit],
    limit: int,
) -> List[FinancialReceiptSemanticHit]:
    merged: List[FinancialReceiptSemanticHit] = []
    seen: set[int] = set()
    for hit in list(primary_hits) + list(secondary_hits):
        if hit.receipt_id in seen:
            continue
        seen.add(hit.receipt_id)
        merged.append(hit)
        if len(merged) >= limit:
            break
    return merged


def search_receipt_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    receipt_ids: Optional[Sequence[int]] = None,
    limit: int = 10,
) -> List[FinancialReceiptSemanticHit]:
    scoped_ids = list(dict.fromkeys(receipt_ids or []))
    owner_id = owner_filter_id(current_user)

    semantic_hits: List[FinancialReceiptSemanticHit] = []
    semantic_available = False
    if mode in {"vector", "hybrid"}:
        ensure_receipt_embeddings(db, current_user=current_user, receipt_ids=scoped_ids or None)
        try:
            semantic_rows = search_financial_receipt_hits_semantic(
                db=db,
                query_text=query_text,
                owner_id=owner_id,
                receipt_ids=scoped_ids or None,
                limit=limit,
            )
            semantic_hits = [build_semantic_hit(row, match_source="semantic") for row in semantic_rows]
            semantic_available = True
        except Exception:
            semantic_hits = []

    needs_text = mode in {"keyword", "hybrid"} or (mode == "vector" and not semantic_available)
    text_match_source = "text"
    if mode == "vector" and not semantic_available:
        text_match_source = "text_fallback"

    text_hits: List[FinancialReceiptSemanticHit] = []
    if needs_text:
        text_rows = search_financial_receipts_text(
            db=db,
            query_text=query_text,
            owner_id=owner_id,
            receipt_ids=scoped_ids or None,
            limit=limit,
        )
        text_hits = [build_text_hit(receipt, match_source=text_match_source) for receipt in text_rows]

    if mode == "keyword":
        return text_hits[:limit]
    if mode == "vector":
        return semantic_hits[:limit] if semantic_available else text_hits[:limit]
    return merge_receipt_hits(semantic_hits, text_hits, limit=limit)


def list_text_receipts(
    db: Session,
    current_user: User,
    query_text: str,
    receipt_ids: Optional[Sequence[int]] = None,
    limit: int = 50,
):
    receipts = search_financial_receipts_text(
        db=db,
        query_text=query_text,
        owner_id=owner_filter_id(current_user),
        receipt_ids=list(receipt_ids) if receipt_ids is not None else None,
        limit=limit,
    )
    return [receipt_to_out(receipt) for receipt in receipts]


def validate_receipt_scope(
    db: Session,
    current_user: User,
    receipt_ids: Sequence[int],
) -> list[int]:
    validated_ids: list[int] = []
    for receipt_id in list(dict.fromkeys(receipt_ids)):
        get_receipt_or_404(db, receipt_id, current_user)
        validated_ids.append(receipt_id)
    return validated_ids
