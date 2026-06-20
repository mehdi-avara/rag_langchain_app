from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from components.llm import llm_client, raise_llm_exception
from db.init_db import get_db
from deps import require_permission
from Models import User
from settings import get_settings

from ..schemas import SupplierAskRequest, SupplierAskResponse
from ..search.service import search_supplier_hits, validate_supplier_scope

router = APIRouter(prefix="/suppliers")
settings = get_settings()
_CITATION_PATTERN = re.compile(r"\[supplier:(\d+)\]")


def _build_context(references) -> str:
    if not references:
        return "(no supplier references)"

    lines = ["Supplier references:"]

    for item in references:
        lines.append(
            f"[supplier:{item.supplier_id}] "
            f"code={item.code} "
            f"name={item.name} "
            f"type={item.supplier_type} "
            f"status={item.status} "
            f"country={item.country or '-'} "
            f"city={item.city or '-'} "
            f"notes={item.notes or '-'}"
        )

    return "\n".join(lines)


def _parse_citations(answer: str) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()

    for raw_value in _CITATION_PATTERN.findall(answer or ""):
        supplier_id = int(raw_value)
        if supplier_id not in seen:
            seen.add(supplier_id)
            result.append(supplier_id)

    return result


@router.post("/ask", response_model=SupplierAskResponse)
async def ask_suppliers(
    payload: SupplierAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("supplier_management:ask")),
):
    supplier_ids = validate_supplier_scope(db, current_user, payload.supplier_ids)

    references = search_supplier_hits(
        db=db,
        current_user=current_user,
        query_text=payload.question,
        mode=payload.mode,
        supplier_ids=supplier_ids or None,
        limit=20,
    )

    if not references:
        return SupplierAskResponse(
            answer="No matching supplier references were found.",
            citations=[],
            used_supplier_ids=[],
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
                        "Answer only from the provided supplier references. "
                        "If the references are insufficient, say so. "
                        "Cite facts strictly as [supplier:<supplier_id>]."
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
        raise_llm_exception(exc, "supplier_management.ask")

    answer = (response.choices[0].message.content or "").strip()
    citations = _parse_citations(answer)

    return SupplierAskResponse(
        answer=answer,
        citations=citations,
        used_supplier_ids=[item.supplier_id for item in references],
        references=references,
    )
