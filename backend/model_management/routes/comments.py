from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from db.init_db import get_db
from deps import get_current_user
from Models import User, Comment

from ..models import ModelCommentLink
from ..schemas import ModelCommentLinkCreate, ModelCommentLinkOut, ModelCommentOut
from ..services import get_model_or_404, is_admin


router = APIRouter()


@router.post("/{model_id}/comments", response_model=ModelCommentLinkOut)
def link_comment(
    model_id: int,
    payload: ModelCommentLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)

    comment = db.query(Comment).filter(Comment.id == payload.comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if not is_admin(current_user) and comment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to link this comment")

    link = (
        db.query(ModelCommentLink)
        .filter(
            ModelCommentLink.model_id == model.id,
            ModelCommentLink.comment_id == comment.id,
        )
        .first()
    )
    if link:
        return link

    link = ModelCommentLink(
        model_id=model.id,
        comment_id=comment.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/{model_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_comment(
    model_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = get_model_or_404(db, model_id, current_user)

    link = (
        db.query(ModelCommentLink)
        .filter(
            ModelCommentLink.model_id == model_id,
            ModelCommentLink.comment_id == comment_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/{model_id}/comments", response_model=List[ModelCommentOut])
def list_linked_comments(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    # system_tag_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_model_or_404(db, model_id, current_user)

    query = (
        db.query(Comment, ModelCommentLink)
        .join(ModelCommentLink, ModelCommentLink.comment_id == Comment.id)
        .filter(ModelCommentLink.model_id == model_id)
    )

    if search:
        query = query.filter(
            or_(
                Comment.title.ilike(f"%{search}%"),
                Comment.content.ilike(f"%{search}%"),
            )
        )
    if type:
        query = query.filter(Comment.type == type)
    # if system_tag_id:
    #     query = query.filter(Comment.system_tag_id == system_tag_id)

    rows = (
        query
        .order_by(ModelCommentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[ModelCommentOut] = []
    for comment, link in rows:
        results.append(
            ModelCommentOut(
                id=comment.id,
                user_id=comment.user_id,
                # system_tag_id=comment.system_tag_id,
                title=comment.title,
                # doc_id=comment.doc_id,
                # chunk_id=comment.chunk_id,
                type=comment.type,
                content=comment.content,
                created_at=comment.created_at,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results
