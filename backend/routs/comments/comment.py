import os
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Query
from sqlalchemy.orm import Session

from core.semantic_ask import generate_answer_from_references, parse_semantic_citations
from db.init_db import get_db
from db.search_connector import search_comments_text, search_comments_semantic, search_comment_hits_semantic
from Models import Comment, User, CommentFile
from deps import get_current_user
from schemas.comment import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
)
from schemas.search import (
    TextSearchRequest,
    SemanticCommentSearchRequestWithId,
    CommentSemanticHit,
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


@router.get("", response_model=List[CommentOut])
def list_comments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all comments."""
    comments = db.query(Comment).order_by(Comment.created_at.desc()).all()
    return comments


@router.post("/filter", response_model=List[CommentOut], status_code=status.HTTP_200_OK)
def filter_comments(
    payload: TextSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return search_comments_text(
        db=db,
        query_text=payload.query,
        user_id=current_user.id,
        comment_ids=payload.ids or None,
        limit=payload.limit,
    )


@router.post("/semantic-search", response_model=List[CommentSemanticHit], status_code=status.HTTP_200_OK)
def semantic_search_comments(
    payload: SemanticCommentSearchRequestWithId,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return search_comment_hits_semantic(
        db=db,
        query_text=payload.query,
        user_id=current_user.id,
        comment_ids=payload.ids or None,
        types=payload.types or None,
        limit=top_k,
    )


@router.post("/ask", response_model=CommentAskResponse, status_code=status.HTTP_200_OK)
async def ask_comments(
    payload: CommentAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
):
    """Return a single comment by id."""
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment




@router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new comment.

    We also generate an embedding for the comment content and store it.
    """
    # generate embedding for this comment's text
    # your helper returns List[List[float]], so take the first
    embeddings = generate_embeddings_for_chunks([payload.content])
    embedding_vec = embeddings[0] if embeddings else None

    new_comment = Comment(
        user_id=current_user.id,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        embedding=embedding_vec
    )
    if payload.media_addresses:
        new_comment.files = [
            CommentFile(
                media_address=addr,
                file_name=os.path.basename(addr),
                user_id=current_user.id,
            )
            for addr in payload.media_addresses
        ]

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return new_comment


@router.put("/{comment_id}", response_model=CommentOut)
async def update_comment_text(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update comment content (and re-embed).
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # regenerate embedding for new text
    embeddings = generate_embeddings_for_chunks([payload.content])
    embedding_vec = embeddings[0] if embeddings else None

    comment.content = payload.content
    comment.embedding = embedding_vec

    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a comment by id.
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.delete(comment)
    db.commit()
    return None
