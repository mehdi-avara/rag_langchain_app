import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.semantic_ask import generate_answer_from_references, parse_semantic_citations, stream_answer_from_references
from db.init_db import get_db
from deps import get_current_user
from Models import User

from ..schemas import TagAskRequest, TagAskMultiRequest, TagAskResponse
from ..system_tag import SystemTag
from ..services import (
    get_tag_or_404,
    get_descendant_tag_ids,
)
from .tags import _semantic_search_tag_scope


router = APIRouter()
DOC_TOP_K = 6
COMMENT_TOP_K = 10


def _ask_limits(scope: str) -> tuple[int, int]:
    if scope == "docs":
        return DOC_TOP_K, 0
    if scope == "comments":
        return 0, COMMENT_TOP_K
    return DOC_TOP_K, COMMENT_TOP_K


@router.post("/{tag_id}/ask", response_model=TagAskResponse)
async def ask_tag(
    tag_id: int,
    payload: TagAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)
    tag_ids = get_descendant_tag_ids(db, tag_id, current_user.id)
    doc_top_k, comment_top_k = _ask_limits(payload.scope)

    references = _semantic_search_tag_scope(
        db=db,
        current_user=current_user,
        query=payload.question,
        tag_ids=tag_ids,
        doc_top_k=doc_top_k,
        comment_top_k=comment_top_k,
        types=payload.types,
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)

    return TagAskResponse(
        answer=answer,
        citations=citations,
        used_chunk_ids=used_chunk_ids,
        used_comment_ids=used_comment_ids,
        references=references,
    )


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/ask/stream")
async def ask_tags_stream(
    payload: TagAskMultiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag_ids = list(dict.fromkeys(payload.tag_ids))
    if not tag_ids:
        tag_ids = [row[0] for row in db.query(SystemTag.id).filter(SystemTag.owner_id == current_user.id).all()]

    for provided_tag_id in tag_ids:
        get_tag_or_404(db, provided_tag_id, current_user.id)

    async def event_generator():
        try:
            doc_top_k, comment_top_k = _ask_limits(payload.scope)
            references = _semantic_search_tag_scope(
                db=db,
                current_user=current_user,
                query=payload.question,
                tag_ids=tag_ids,
                doc_top_k=doc_top_k,
                comment_top_k=comment_top_k,
                types=payload.types,
            )
        except Exception as exc:
            yield _sse_event("error", {"message": f"Semantic search failed: {str(exc)}"})
            return

        refs_payload = {
            "tags": list(references.get("tags", []) or []),
            "documents": list(references.get("documents", []) or [])[:doc_top_k],
            "comments": list(references.get("comments", []) or [])[:comment_top_k],
        }
        yield _sse_event("references", {"references": refs_payload})

        chunks = []
        try:
            async for delta in stream_answer_from_references(payload.question, refs_payload):
                chunks.append(delta)
                yield _sse_event("delta", {"text": delta})
        except Exception as exc:
            yield _sse_event("error", {"message": f"Model stream failed: {str(exc)}"})
            return

        answer = "".join(chunks).strip()
        used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)
        yield _sse_event(
            "done",
            {
                "answer": answer,
                "citations": citations,
                "used_chunk_ids": used_chunk_ids,
                "used_comment_ids": used_comment_ids,
                "references": refs_payload,
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/ask", response_model=TagAskResponse)
async def ask_tags(
    payload: TagAskMultiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag_ids = list(dict.fromkeys(payload.tag_ids))
    if not tag_ids:
        tag_ids = [row[0] for row in db.query(SystemTag.id).filter(SystemTag.owner_id == current_user.id).all()]

    for provided_tag_id in tag_ids:
        get_tag_or_404(db, provided_tag_id, current_user.id)
    doc_top_k, comment_top_k = _ask_limits(payload.scope)

    references = _semantic_search_tag_scope(
        db=db,
        current_user=current_user,
        query=payload.question,
        tag_ids=tag_ids,
        doc_top_k=doc_top_k,
        comment_top_k=comment_top_k,
        types=payload.types,
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)

    return TagAskResponse(
        answer=answer,
        citations=citations,
        used_chunk_ids=used_chunk_ids,
        used_comment_ids=used_comment_ids,
        references=references,
    )
