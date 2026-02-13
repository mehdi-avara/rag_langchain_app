from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import User
from core.agents import build_answer_graph, GraphState

from ..schemas import ModelAskRequest, ModelAskMultiRequest, ModelAskResponse
from ..services import (
    get_model_or_404,
    get_doc_ids,
    get_comment_ids,
    get_doc_ids_for_models,
    get_comment_ids_for_models,
)


router = APIRouter()


@router.post("/{model_id}/ask", response_model=ModelAskResponse)
async def ask_model(
    model_id: int,
    payload: ModelAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)

    doc_ids = get_doc_ids(db, model.id)
    comment_ids = get_comment_ids(db, model.id)

    if payload.scope == "docs":
        comment_ids = []
    elif payload.scope == "comments":
        doc_ids = None

    state = GraphState(
        question=payload.question,
        route=payload.route,
        db=db,
        mode=payload.mode,
        doc_ids=doc_ids,
        comment_ids=comment_ids,
        scope=payload.scope
    )


    graph = build_answer_graph()
    result = await graph.ainvoke(state)

    chunks = result.get("chunks", [])
    comments = result.get("comments", [])
    chunk_ids = [c.id for c in chunks]
    comment_ids_used = [c.id for c in comments]

    return ModelAskResponse(
        answer=result.get("answer", ""),
        citations=chunk_ids,
        used_chunk_ids=chunk_ids,
        used_comment_ids=comment_ids_used,
    )


@router.post("/ask", response_model=ModelAskResponse)
async def ask_models(
    payload: ModelAskMultiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model_ids = list(dict.fromkeys(payload.model_ids))

    for model_id in model_ids:
        get_model_or_404(db, model_id, current_user)

    doc_ids = get_doc_ids_for_models(db, model_ids)
    comment_ids = get_comment_ids_for_models(db, model_ids)

    if payload.scope == "docs":
        comment_ids = []
    elif payload.scope == "comments":
        doc_ids = None

    state = GraphState(
        question=payload.question,
        route=payload.route,
        db=db,
        mode=payload.mode,
        doc_ids=doc_ids,
        comment_ids=comment_ids,
        scope=payload.scope,
    )

    graph = build_answer_graph()
    result = await graph.ainvoke(state)

    chunks = result.get("chunks", [])
    comments = result.get("comments", [])
    chunk_ids = [c.id for c in chunks]
    comment_ids_used = [c.id for c in comments]

    return ModelAskResponse(
        answer=result.get("answer", ""),
        citations=chunk_ids,
        used_chunk_ids=chunk_ids,
        used_comment_ids=comment_ids_used,
    )
