from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission
from shared.phase1_ask import answer_from_references, parse_citations

from ..search.schemas import (
    GoodsReceiptAskRequest,
    GoodsReceiptAskResponse,
)
from ..search.service import (
    search_goods_receipt_hits,
    validate_goods_receipt_scope,
)

router = APIRouter()


def _build_context(references) -> str:
    if not references:
        return "(no goods receipt references)"

    return "\n".join(
        (
            f"[grn:{item.goods_receipt_id}] "
            f"number={item.grn_number} "
            f"status={item.status} "
            f"receipt_date={item.receipt_date} "
            f"delivery_note_number={item.delivery_note_number or '-'} "
            f"warehouse_id={item.warehouse_id or '-'} "
            f"item_codes={','.join(item.item_codes) or '-'}"
        )
        for item in references
    )


@router.post("/ask", response_model=GoodsReceiptAskResponse)
async def ask_goods_receipt_notes(
    payload: GoodsReceiptAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("goods_receipt_management:ask")
    ),
):
    goods_receipt_ids = validate_goods_receipt_scope(
        db,
        current_user,
        payload.goods_receipt_ids,
    )

    references = search_goods_receipt_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        goods_receipt_ids=goods_receipt_ids,
        limit=20,
    )

    if not references:
        return GoodsReceiptAskResponse(
            answer="No matching goods receipt references were found.",
            citations=[],
            used_goods_receipt_ids=[],
            references=[],
        )

    answer = await answer_from_references(
        question=payload.question,
        references=references,
        context=_build_context(references),
        citation_prefix="grn",
        component_name="goods_receipt_management.ask",
    )

    return GoodsReceiptAskResponse(
        answer=answer,
        citations=parse_citations(answer, "grn"),
        used_goods_receipt_ids=[
            item.goods_receipt_id
            for item in references
        ],
        references=references,
    )
