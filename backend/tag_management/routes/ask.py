from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import User
from core.agents import build_answer_graph, GraphState

from ..schemas import TagAskRequest, TagAskMultiRequest, TagAskResponse
from ..services import (
    get_tag_or_404,
    get_doc_ids_for_tags,
    get_comment_ids_for_tags,
    get_descendant_tag_ids,
)


router = APIRouter()


@router.post("/{tag_id}/ask", response_model=TagAskResponse)
async def ask_tag(
    tag_id: int,
    payload: TagAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag = get_tag_or_404(db, tag_id, current_user.id)

    tag_ids = get_descendant_tag_ids(db, tag.id, current_user.id)
    doc_ids = get_doc_ids_for_tags(db, tag_ids)
    comment_ids = get_comment_ids_for_tags(db, tag_ids)

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

    return TagAskResponse(
        answer=result.get("answer", ""),
        citations=chunk_ids,
        used_chunk_ids=chunk_ids,
        used_comment_ids=comment_ids_used,
    )


@router.post("/ask", response_model=TagAskResponse)
async def ask_tags(
    payload: TagAskMultiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag_ids = list(dict.fromkeys(payload.tag_ids))

    for tag_id in tag_ids:
        get_tag_or_404(db, tag_id, current_user.id)

    doc_ids = get_doc_ids_for_tags(db, tag_ids)
    comment_ids = get_comment_ids_for_tags(db, tag_ids)

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

    return TagAskResponse(
        answer=result.get("answer", ""),
        citations=chunk_ids,
        used_chunk_ids=chunk_ids,
        used_comment_ids=comment_ids_used,
    )
