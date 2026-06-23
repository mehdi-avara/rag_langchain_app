from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models.user import User
from db.init_db import get_db
from deps import require_permission
from shared.phase1_ask import answer_from_references, parse_citations

from ..search.schemas import WarehouseAskRequest, WarehouseAskResponse
from ..search.service import search_warehouse_hits, validate_stock_scope

router = APIRouter()


def _build_context(references) -> str:
    if not references:
        return "(no warehouse stock references)"

    return "\n".join(
        (
            f"[stock:{item.stock_item_id}] "
            f"item_code={item.item_code} "
            f"item_name={item.item_name} "
            f"warehouse={item.warehouse_code} "
            f"location={item.storage_location_code} "
            f"quantity_on_hand={item.quantity_on_hand} "
            f"quantity_reserved={item.quantity_reserved} "
            f"quantity_available={item.quantity_available} "
            f"inventory_value_base={item.inventory_value_base}"
        )
        for item in references
    )


@router.post("/ask", response_model=WarehouseAskResponse)
async def ask_warehouse_stock(
    payload: WarehouseAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission("warehouse_management:ask")
    ),
):
    stock_item_ids = validate_stock_scope(
        db,
        current_user,
        payload.stock_item_ids,
    )

    references = search_warehouse_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        stock_item_ids=stock_item_ids,
        warehouse_id=payload.warehouse_id,
        storage_location_id=payload.storage_location_id,
        limit=20,
    )

    if not references:
        return WarehouseAskResponse(
            answer="No matching warehouse stock references were found.",
            citations=[],
            used_stock_item_ids=[],
            references=[],
        )

    answer = await answer_from_references(
        question=payload.question,
        references=references,
        context=_build_context(references),
        citation_prefix="stock",
        component_name="warehouse_management.ask",
    )

    return WarehouseAskResponse(
        answer=answer,
        citations=parse_citations(answer, "stock"),
        used_stock_item_ids=[
            item.stock_item_id
            for item in references
        ],
        references=references,
    )
