from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.semantic_ask import generate_answer_from_references, parse_semantic_citations
from db.init_db import get_db
from deps import require_permission
from Models import User

from ..models import ManagedModel
from ..schemas import ModelAskRequest, ModelAskMultiRequest, ModelAskResponse
from ..services import (
    get_model_or_404,
    is_admin,
)
from .models import _semantic_search_model_scope


router = APIRouter()
DOC_TOP_K = 6
COMMENT_TOP_K = 10


def _ask_limits(scope: str) -> tuple[int, int]:
    if scope == "docs":
        return DOC_TOP_K, 0
    if scope == "comments":
        return 0, COMMENT_TOP_K
    return DOC_TOP_K, COMMENT_TOP_K


@router.post("/{model_id}/ask", response_model=ModelAskResponse)
async def ask_model(
    model_id: int,
    payload: ModelAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:ask")),
):
    model = get_model_or_404(db, model_id, current_user)
    doc_top_k, comment_top_k = _ask_limits(payload.scope)

    references = _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.question,
        model_ids=[model.id],
        doc_top_k=doc_top_k,
        comment_top_k=comment_top_k,
        types=payload.types,
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)

    return ModelAskResponse(
        answer=answer,
        citations=citations,
        used_chunk_ids=used_chunk_ids,
        used_comment_ids=used_comment_ids,
        references=references,
    )


@router.post("/ask", response_model=ModelAskResponse)
async def ask_models(
    payload: ModelAskMultiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:ask")),
):
    model_ids = list(dict.fromkeys(payload.model_ids))
    if not model_ids:
        query = db.query(ManagedModel.id)
        if not is_admin(current_user):
            query = query.filter(ManagedModel.owner_id == current_user.id)
        model_ids = [row[0] for row in query.all()]

    for provided_model_id in model_ids:
        get_model_or_404(db, provided_model_id, current_user)

    doc_top_k, comment_top_k = _ask_limits(payload.scope)

    references = _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.question,
        model_ids=model_ids,
        doc_top_k=doc_top_k,
        comment_top_k=comment_top_k,
        types=payload.types,
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)

    return ModelAskResponse(
        answer=answer,
        citations=citations,
        used_chunk_ids=used_chunk_ids,
        used_comment_ids=used_comment_ids,
        references=references,
    )