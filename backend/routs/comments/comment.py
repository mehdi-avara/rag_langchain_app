from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from core.semantic_ask import generate_answer_from_references, parse_semantic_citations
from db.init_db import get_db
from db.search_connector import search_comments_text, search_comment_hits_semantic
from Models import Comment, User
from deps import get_current_user, require_permission
from schemas.comment import CommentCreate, CommentOut, CommentUpdate
from schemas.search import (
    TextSearchRequest,
    SemanticCommentSearchRequestWithId,
    CommentSemanticHit,
    CommentSearchRequest,
    CommentSearchResponse,
    CommentAskRequest,
    CommentAskResponse,
)
from components import generate_embeddings_for_chunks
from .files import router as files_router

router = APIRouter(tags=["comments"])

router.include_router(
    files_router,
    prefix="/files"
)


def _get_owned_comment(db: Session, comment_id: int, current_user: User) -> Comment:
    comment = (
        db.query(Comment)
        .filter(Comment.id == comment_id, Comment.user_id == current_user.id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("", response_model=List[CommentOut])
def list_comments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:read")),
):
    return (
        db.query(Comment)
        .filter(Comment.user_id == current_user.id)
        .order_by(Comment.created_at.desc())
        .all()
    )


@router.post("/search", response_model=CommentSearchResponse, status_code=status.HTTP_200_OK)
def search_comments(
    payload: CommentSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:search")),
):
    mode = "semantic" if payload.mode == "vector" else payload.mode

    comments = []
    hits = []

    if mode in {"keyword", "hybrid"}:
        comments = search_comments_text(
            db=db,
            query_text=payload.query,
            user_id=current_user.id,
            comment_ids=payload.ids or None,
            limit=payload.limit,
        )

    if mode in {"semantic", "hybrid"}:
        hits = search_comment_hits_semantic(
            db=db,
            query_text=payload.query,
            user_id=current_user.id,
            comment_ids=payload.ids or None,
            types=payload.types or None,
            limit=payload.limit,
        )

    return {
        "mode": mode,
        "comments": comments,
        "hits": hits,
    }


@router.post("/filter", response_model=List[CommentOut], status_code=status.HTTP_200_OK, deprecated=True)
def filter_comments(
    payload: TextSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:search")),
):
    result = search_comments(
        payload=CommentSearchRequest(
            query=payload.query,
            ids=payload.ids,
            mode="keyword",
            limit=payload.limit,
        ),
        db=db,
        current_user=current_user,
    )
    return result["comments"]


@router.post("/semantic-search", response_model=List[CommentSemanticHit], status_code=status.HTTP_200_OK, deprecated=True)
def semantic_search_comments(
    payload: SemanticCommentSearchRequestWithId,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:search")),
):
    result = search_comments(
        payload=CommentSearchRequest(
            query=payload.query,
            ids=payload.ids,
            types=payload.types,
            mode="semantic",
            limit=top_k,
        ),
        db=db,
        current_user=current_user,
    )
    return result["hits"]


@router.post("/ask", response_model=CommentAskResponse, status_code=status.HTTP_200_OK)
async def ask_comments(
    payload: CommentAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:ask")),
):
    comment_top_k = 10 if payload.scope in {"comments", "both"} else 0
    references = (
        search_comment_hits_semantic(
            db=db,
            query_text=payload.question,
            user_id=current_user.id,
            comment_ids=None,
            types=payload.types or None,
            limit=comment_top_k,
        )
        if comment_top_k > 0
        else []
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)
    return {
        "answer": answer,
        "citations": citations,
        "used_chunk_ids": used_chunk_ids,
        "used_comment_ids": used_comment_ids,
        "references": references,
    }


@router.get("/{comment_id}", response_model=CommentOut)
def get_comment_by_id(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:read")),
):
    return _get_owned_comment(db, comment_id, current_user)


@router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:create")),
):
    embedding_vec = None
    try:
        embeddings = generate_embeddings_for_chunks([f"search_document: {payload.content}"])
        embedding_vec = embeddings[0] if embeddings else None
    except Exception:
        embedding_vec = None

    new_comment = Comment(
        user_id=current_user.id,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        embedding=embedding_vec,
    )

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return new_comment


@router.patch("/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:update")),
):
    comment = _get_owned_comment(db, comment_id, current_user)

    data = payload.model_dump(exclude_unset=True)

    if "content" in data and data["content"] is not None:
        try:
            embeddings = generate_embeddings_for_chunks([f"search_document: {data['content']}"])
            comment.embedding = embeddings[0] if embeddings else None
        except Exception:
            comment.embedding = None

    for key, value in data.items():
        setattr(comment, key, value)

    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:delete")),
):
    comment = _get_owned_comment(db, comment_id, current_user)

    db.delete(comment)
    db.commit()
    return None
