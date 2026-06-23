from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy.orm import Session

from Models.user import User
from material_management.search.service import search_item_hits

from ..models import MaterialRequisition
from ..services import get_requisition_or_404, search_requisitions
from .repository import search_requisitions_by_item_ids
from .schemas import RequisitionSearchHit


def validate_requisition_scope(
    db: Session,
    current_user: User,
    requisition_ids: Sequence[int],
) -> list[int]:
    result: list[int] = []

    for requisition_id in list(dict.fromkeys(requisition_ids)):
        get_requisition_or_404(
            db=db,
            current_user=current_user,
            requisition_id=requisition_id,
        )
        result.append(requisition_id)

    return result


def _to_hit(
    requisition: MaterialRequisition,
    match_source: str,
) -> RequisitionSearchHit:
    items = list(getattr(requisition, "items", []) or [])

    return RequisitionSearchHit(
        requisition_id=requisition.id,
        company_id=requisition.company_id,
        mr_number=requisition.mr_number,
        status=requisition.status,
        priority=requisition.priority,
        reason=requisition.reason,
        needed_by_date=requisition.needed_by_date,
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
    primary: Iterable[RequisitionSearchHit],
    secondary: Iterable[RequisitionSearchHit],
    limit: int,
) -> list[RequisitionSearchHit]:
    result: list[RequisitionSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary) + list(secondary):
        if hit.requisition_id in seen:
            continue

        seen.add(hit.requisition_id)
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


def search_requisition_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    requisition_ids: Sequence[int] | None = None,
    limit: int = 20,
) -> list[RequisitionSearchHit]:
    scoped_ids = list(dict.fromkeys(requisition_ids or []))
    semantic_hits: list[RequisitionSearchHit] = []

    if mode in {"vector", "hybrid"}:
        item_ids, source = _semantic_item_ids(
            db=db,
            current_user=current_user,
            query_text=query_text,
            limit=limit,
        )

        semantic_hits = [
            _to_hit(record, source)
            for record in search_requisitions_by_item_ids(
                db=db,
                current_user=current_user,
                item_ids=item_ids,
                requisition_ids=scoped_ids or None,
                limit=limit,
            )
        ]

    keyword_hits: list[RequisitionSearchHit] = []

    if mode in {"keyword", "hybrid"} or (
        mode == "vector" and not semantic_hits
    ):
        source = "text_fallback" if mode == "vector" else "keyword"

        keyword_hits = [
            _to_hit(record, source)
            for record in search_requisitions(
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
