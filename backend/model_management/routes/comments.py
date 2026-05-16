from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from db.init_db import get_db
from deps import require_permission
from Models import User, Comment

from ..models import ModelCommentLink
from ..schemas import (
    ModelCommentLinkCreate,
    ModelCommentLinkOut,
    ModelCommentOut,
    ModelCreateCommentAndLinkRequest,
)
from routs.comments.comment import create_comment, _get_owned_comment
from ..services import get_model_or_404


router = APIRouter()


@router.post("/{model_id}/comments", response_model=ModelCommentLinkOut)
def link_comment(
    model_id: int,
    payload: ModelCommentLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:comments")),
):
    model = get_model_or_404(db, model_id, current_user)

    comment = _get_owned_comment(db, payload.comment_id, current_user)

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


@router.post("/{model_id}/comments/create", response_model=ModelCommentLinkOut, status_code=status.HTTP_201_CREATED)
async def create_comment_and_link(
    model_id: int,
    body: ModelCreateCommentAndLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:comments")),
):
    _ = get_model_or_404(db, model_id, current_user)

    comment = await create_comment(payload=body.payload, db=db, current_user=current_user)
    payload = ModelCommentLinkCreate(comment_id=comment.id, note=body.link_description)
    return link_comment(model_id=model_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{model_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_comment(
    model_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:comments")),
):
    _ = get_model_or_404(db, model_id, current_user)
    _get_owned_comment(db, comment_id, current_user)

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
    current_user: User = Depends(require_permission("models:comments")),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_model_or_404(db, model_id, current_user)

    query = (
        db.query(Comment, ModelCommentLink)
        .join(ModelCommentLink, ModelCommentLink.comment_id == Comment.id)
        .join(User, User.id == Comment.user_id)
        .filter(
            ModelCommentLink.model_id == model_id,
            Comment.user_id == current_user.id,
        )
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
                title=comment.title,
                type=comment.type,
                content=comment.content,
                created_at=comment.created_at,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results
