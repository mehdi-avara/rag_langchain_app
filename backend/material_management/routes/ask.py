from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from Models import User
from components.llm import llm_client, raise_llm_exception
from db.init_db import get_db
from deps import require_permission
from settings import get_settings

from ..schemas import ItemAskRequest, ItemAskResponse
from ..search.service import search_item_hits, validate_item_scope

router = APIRouter()
settings = get_settings()
_CITATION_PATTERN = re.compile(r"\[item:(\d+)\]")


def _build_context(references) -> str:
    if not references:
        return "(no item references)"

    lines = ["Item references:"]

    for item in references:
        lines.append(
            f"[item:{item.item_id}] "
            f"code={item.item_code} "
            f"name={item.name} "
            f"type={item.item_type} "
            f"category_id={item.category_id} "
            f"unit_id={item.unit_id} "
            f"critical={item.is_critical} "
            f"active={item.is_active} "
            f"description={item.description or '-'}"
        )

    return "\n".join(lines)


def _parse_citations(answer: str) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()

    for raw_value in _CITATION_PATTERN.findall(answer or ""):
        item_id = int(raw_value)
        if item_id not in seen:
            seen.add(item_id)
            result.append(item_id)

    return result


@router.post("/ask", response_model=ItemAskResponse)
async def ask_items(
    payload: ItemAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("material_management:ask")),
):
    item_ids = validate_item_scope(db, current_user, payload.item_ids)

    references = search_item_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        item_ids=item_ids or None,
        limit=20,
    )

    if not references:
        return ItemAskResponse(
            answer="No matching item references were found.",
            citations=[],
            used_item_ids=[],
            references=[],
        )

    try:
        response = await llm_client.async_openai_client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided item references. "
                        "If the references are insufficient, say so. "
                        "Cite facts strictly as [item:<item_id>]."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{payload.question}\n\n"
                        f"References:\n{_build_context(references)}"
                    ),
                },
            ],
        )
    except Exception as exc:
        raise_llm_exception(exc, "material_management.ask")

    answer = (response.choices[0].message.content or "").strip()

    return ItemAskResponse(
        answer=answer,
        citations=_parse_citations(answer),
        used_item_ids=[item.item_id for item in references],
        references=references,
    )
