from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User, Comment, CommentType

from ..models import TagCommentLink
from ..schemas import (
    TagCommentOut,
    TagCommentLinkCreate,
    TagCommentLinkOut,
    TagCreateCommentAndLinkRequest,
)
from routs.comments.comment import create_comment
from ..services import get_tag_or_404, is_admin


router = APIRouter()


@router.post("/{tag_id}/comments", response_model=TagCommentLinkOut, status_code=status.HTTP_201_CREATED)
def link_comment(
    tag_id: int,
    payload: TagCommentLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:comments")),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    comment = db.query(Comment).filter(Comment.id == payload.comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if not is_admin(current_user) and comment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to link this comment")

    link = (
        db.query(TagCommentLink)
        .filter(
            TagCommentLink.tag_id == tag_id,
            TagCommentLink.comment_id == comment.id,
        )
        .first()
    )
    if link:
        link.note = payload.note
        db.commit()
        db.refresh(link)
        return link

    link = TagCommentLink(
        tag_id=tag_id,
        comment_id=comment.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.post("/{tag_id}/comments/create", response_model=TagCommentLinkOut, status_code=status.HTTP_201_CREATED)
async def create_comment_and_link(
    tag_id: int,
    body: TagCreateCommentAndLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:comments")),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    comment = await create_comment(payload=body.payload, db=db, current_user=current_user)
    payload = TagCommentLinkCreate(comment_id=comment.id, note=body.link_description)
    return link_comment(tag_id=tag_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{tag_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_comment(
    tag_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:comments")),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    link = (
        db.query(TagCommentLink)
        .filter(
            TagCommentLink.tag_id == tag_id,
            TagCommentLink.comment_id == comment_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/{tag_id}/comments", response_model=List[TagCommentOut], status_code=status.HTTP_200_OK)
def list_tag_comments(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:comments")),
    search: Optional[str] = Query(None),
    type: Optional[CommentType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    query = (
        db.query(Comment, TagCommentLink)
        .join(TagCommentLink, TagCommentLink.comment_id == Comment.id)
        .filter(TagCommentLink.tag_id == tag_id)
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
        .order_by(TagCommentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[TagCommentOut] = []
    for comment, link in rows:
        results.append(
            TagCommentOut(
                id=comment.id,
                user_id=comment.user_id,
                system_tag_id=link.tag_id,
                title=comment.title,
                type=comment.type,
                content=comment.content,
                created_at=comment.created_at,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results