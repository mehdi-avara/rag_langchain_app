from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy.orm import Session

from Models.user import User
from material_management.search.service import search_item_hits

from ..models import RequestForQuotation
from ..services import get_rfq_or_404, search_rfqs
from .repository import search_rfqs_by_item_ids
from .schemas import RFQSearchHit


def validate_rfq_scope(
    db: Session,
    current_user: User,
    rfq_ids: Sequence[int],
) -> list[int]:
    result: list[int] = []

    for rfq_id in list(dict.fromkeys(rfq_ids)):
        get_rfq_or_404(
            db=db,
            current_user=current_user,
            rfq_id=rfq_id,
        )
        result.append(rfq_id)

    return result


def _to_hit(
    rfq: RequestForQuotation,
    match_source: str,
) -> RFQSearchHit:
    items = list(getattr(rfq, "items", []) or [])

    return RFQSearchHit(
        rfq_id=rfq.id,
        company_id=rfq.company_id,
        rfq_number=rfq.rfq_number,
        status=rfq.status,
        title=rfq.title,
        description=rfq.description,
        deadline_date=rfq.deadline_date,
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
    primary: Iterable[RFQSearchHit],
    secondary: Iterable[RFQSearchHit],
    limit: int,
) -> list[RFQSearchHit]:
    result: list[RFQSearchHit] = []
    seen: set[int] = set()

    for hit in list(primary) + list(secondary):
        if hit.rfq_id in seen:
            continue

        seen.add(hit.rfq_id)
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


def search_rfq_hits(
    db: Session,
    current_user: User,
    query_text: str,
    mode: str,
    rfq_ids: Sequence[int] | None = None,
    limit: int = 20,
) -> list[RFQSearchHit]:
    scoped_ids = list(dict.fromkeys(rfq_ids or []))
    semantic_hits: list[RFQSearchHit] = []

    if mode in {"vector", "hybrid"}:
        item_ids, source = _semantic_item_ids(
            db=db,
            current_user=current_user,
            query_text=query_text,
            limit=limit,
        )

        semantic_hits = [
            _to_hit(record, source)
            for record in search_rfqs_by_item_ids(
                db=db,
                current_user=current_user,
                item_ids=item_ids,
                rfq_ids=scoped_ids or None,
                limit=limit,
            )
        ]

    keyword_hits: list[RFQSearchHit] = []

    if mode in {"keyword", "hybrid"} or (
        mode == "vector" and not semantic_hits
    ):
        source = "text_fallback" if mode == "vector" else "keyword"

        keyword_hits = [
            _to_hit(record, source)
            for record in search_rfqs(
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
