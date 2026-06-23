from __future__ import annotations

from collections.abc import Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from Models.user import User
from material_management.search.service import search_item_hits

from ..models import GoodsReceiptNote
from ..services import search_goods_receipts, tenant_id
from .repository import search_goods_receipts_by_item_ids
from .schemas import GoodsReceiptSearchHit


def validate_goods_receipt_scope(
    db: Session,
    current_user: User,
    goods_receipt_ids: Sequence[int],
) -> list[int]:
    ids = list(dict.fromkeys(goods_receipt_ids))

    if not ids:
        return []

    existing_ids = {
        row[0]
        for row in (
            db.query(GoodsReceiptNote.id)
            .filter(
                GoodsReceiptNote.company_id == tenant_id(current_user),
                GoodsReceiptNote.id.in_(ids),
            )
            .all()
        )
    }

    missing = [value for value in ids if value not in existing_ids]

    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goods receipt note not found",
        )

    return ids


def _to_hit(
    goods_receipt: GoodsReceiptNote,
    match_source: str,
) -> GoodsReceiptSearchHit:
    items = list(getattr(goods_receipt, "items", []) or [])

    return GoodsReceiptSearchHit(
        goods_receipt_id=goods_receipt.id,
        company_id=goods_receipt.company_id,
        grn_number=goods_receipt.grn_number,
        status=goods_receipt.status,
        receipt_date=goods_receipt.receipt_date,
        delivery_note_number=goods_receipt.delivery_note_number,
        warehouse_id=goods_receipt.warehouse_id,
        item_ids=[
            item.item_id
            for item in items
            if getattr(item, "item_id", None) is not None
        ],
        item_codes=[
            item.item_code
            for item in items
            if getattr(item, "item_code", None)
        ],
        match_source=match_source,
    )


def _merge_hits(
    primary: Iterable[GoodsReceiptSearchHit],
    secondary: Iterable[GoodsReceiptSearchHit],
    limit: int,
) -> list[GoodsReceiptSearchHit]:
    result: list[GoodsReceiptSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary) + list(secondary):
        if hit.goods_receipt_id in seen:
            continue

        seen.add(hit.goods_receipt_id)
        result.append(hit)

        if len(result) >= limit:
            break

    return result


def _semantic_item_ids(
    db: Session,
    current_user: User,
    query_text: str,
    limit: int,
) -> tuple[list[int], str]:
    try:
        item_hits = search_item_hits(
            db=db,
            current_user=current_user,
            query_text=query_text,
            mode="vector",
            limit=limit,
        )
    except Exception:
        return [], "item_text_fallback"

    item_ids = [
        hit.item_id
        for hit in item_hits
        if getattr(hit, "item_id", None) is not None
    ]

    source = (
        "semantic_item"
        if any(
            getattr(hit, "match_source", None) == "semantic"
            for hit in item_hits
        )
        else "item_text_fallback"
    )

    return item_ids, source


def search_goods_receipt_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    goods_receipt_ids: Sequence[int] | None = None,
    limit: int = 20,
) -> list[GoodsReceiptSearchHit]:
    scoped_ids = list(dict.fromkeys(goods_receipt_ids or []))
    semantic_hits: list[GoodsReceiptSearchHit] = []

    if mode in {"vector", "hybrid"}:
        item_ids, source = _semantic_item_ids(
            db=db,
            current_user=current_user,
            query_text=query_text,
            limit=limit,
        )

        semantic_hits = [
            _to_hit(record, source)
            for record in search_goods_receipts_by_item_ids(
                db=db,
                current_user=current_user,
                item_ids=item_ids,
                goods_receipt_ids=scoped_ids or None,
                limit=limit,
            )
        ]

    keyword_hits: list[GoodsReceiptSearchHit] = []

    if mode in {"keyword", "hybrid"} or (
        mode == "vector" and not semantic_hits
    ):
        source = "text_fallback" if mode == "vector" else "keyword"

        keyword_hits = [
            _to_hit(record, source)
            for record in search_goods_receipts(
                db=db,
                current_user=current_user,
                query_text=query_text,
                page=1,
                size=limit,
            )
            if not scoped_ids or record.id in scoped_ids
        ]

    if mode == "keyword":
        return keyword_hits[:limit]

    if mode == "vector":
        return semantic_hits[:limit] or keyword_hits[:limit]

    return _merge_hits(semantic_hits, keyword_hits, limit)
