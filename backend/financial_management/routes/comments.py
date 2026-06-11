from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import Comment, User

from routs.comments.comment import create_comment

from ..models import FinancialReceiptCommentLink
from ..schemas import (
    FinancialCreateCommentAndLinkRequest,
    FinancialReceiptCommentLinkCreate,
    FinancialReceiptCommentLinkOut,
    FinancialReceiptCommentOut,
    FinancialReceiptLinkSearchRequest,
)
from ..services import get_receipt_or_404, safe_embed_text


router = APIRouter(prefix="/receipts")


def _get_comment_or_404(db: Session, comment_id: int, current_user: User) -> Comment:
    comment = (
        db.query(Comment)
        .filter(
            Comment.id == comment_id,
            Comment.user_id == current_user.id,
        )
        .first()
    )

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    return comment


def _search_receipt_comment_note_ids(
    db: Session,
    receipt_id: int,
    query: str,
    mode: str,
    limit: int,
) -> list[int]:
    matched_ids: list[int] = []
    pattern = f"%{query}%"

    if mode in {"keyword", "hybrid"}:
        rows = (
            db.query(FinancialReceiptCommentLink.comment_id)
            .filter(
                FinancialReceiptCommentLink.receipt_id == receipt_id,
                FinancialReceiptCommentLink.note.ilike(pattern),
            )
            .limit(limit)
            .all()
        )
        matched_ids.extend([row[0] for row in rows])

    if mode in {"semantic", "vector", "hybrid"}:
        query_embedding = safe_embed_text(query)
        if query_embedding is not None:
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
            rows = db.execute(
                text(
                    """
                    SELECT comment_id
                    FROM financial_receipt_comment_links
                    WHERE receipt_id = :receipt_id
                      AND note_embedding IS NOT NULL
                    ORDER BY (1 - (note_embedding <=> (:query_vec)::vector)) DESC
                    LIMIT :limit
                    """
                ),
                {
                    "receipt_id": receipt_id,
                    "query_vec": embedding_str,
                    "limit": limit,
                },
            ).fetchall()
            matched_ids.extend([row.comment_id for row in rows])

    seen: set[int] = set()
    output: list[int] = []

    for comment_id in matched_ids:
        if comment_id in seen:
            continue
        seen.add(comment_id)
        output.append(comment_id)

    return output[:limit]


@router.post("/{receipt_id}/comments", response_model=FinancialReceiptCommentLinkOut, status_code=status.HTTP_201_CREATED)
def link_comment(
    receipt_id: int,
    payload: FinancialReceiptCommentLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_comments:create")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    comment = _get_comment_or_404(db, payload.comment_id, current_user)

    link = (
        db.query(FinancialReceiptCommentLink)
        .filter(
            FinancialReceiptCommentLink.receipt_id == receipt_id,
            FinancialReceiptCommentLink.comment_id == comment.id,
        )
        .first()
    )

    note_embedding = safe_embed_text(payload.note) if payload.note else None

    if link:
        link.note = payload.note
        link.note_embedding = note_embedding
        db.commit()
        db.refresh(link)
        return link

    link = FinancialReceiptCommentLink(
        receipt_id=receipt_id,
        comment_id=comment.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
        note_embedding=note_embedding,
    )

    db.add(link)
    db.commit()
    db.refresh(link)

    return link


@router.post("/{receipt_id}/comments/create", response_model=FinancialReceiptCommentLinkOut, status_code=status.HTTP_201_CREATED)
async def create_comment_and_link(
    receipt_id: int,
    body: FinancialCreateCommentAndLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_comments:create")),
):
    get_receipt_or_404(db, receipt_id, current_user)

    comment = await create_comment(payload=body.payload, db=db, current_user=current_user)

    payload = FinancialReceiptCommentLinkCreate(
        comment_id=comment.id,
        note=body.link_description,
    )

    return link_comment(receipt_id=receipt_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{receipt_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_comment(
    receipt_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_comments:delete")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    _get_comment_or_404(db, comment_id, current_user)

    link = (
        db.query(FinancialReceiptCommentLink)
        .filter(
            FinancialReceiptCommentLink.receipt_id == receipt_id,
            FinancialReceiptCommentLink.comment_id == comment_id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()

    return None


@router.get("/{receipt_id}/comments", response_model=List[FinancialReceiptCommentOut])
def list_receipt_comments(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_comments:read")),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    get_receipt_or_404(db, receipt_id, current_user)

    query = (
        db.query(Comment, FinancialReceiptCommentLink)
        .join(FinancialReceiptCommentLink, FinancialReceiptCommentLink.comment_id == Comment.id)
        .filter(
            FinancialReceiptCommentLink.receipt_id == receipt_id,
            Comment.user_id == current_user.id,
        )
    )

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Comment.title.ilike(pattern),
                Comment.content.ilike(pattern),
                FinancialReceiptCommentLink.note.ilike(pattern),
            )
        )

    rows = (
        query
        .order_by(FinancialReceiptCommentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        FinancialReceiptCommentOut(
            id=comment.id,
            user_id=comment.user_id,
            title=comment.title,
            type=comment.type,
            content=comment.content,
            created_at=comment.created_at,
            note=link.note,
            linked_at=link.created_at,
        )
        for comment, link in rows
    ]


@router.post("/{receipt_id}/comments/search", response_model=List[FinancialReceiptCommentOut])
def search_receipt_comments(
    receipt_id: int,
    payload: FinancialReceiptLinkSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_comments:search")),
):
    get_receipt_or_404(db, receipt_id, current_user)

    matched_note_ids = _search_receipt_comment_note_ids(
        db=db,
        receipt_id=receipt_id,
        query=payload.query,
        mode=payload.mode,
        limit=payload.limit,
    )

    query = (
        db.query(Comment, FinancialReceiptCommentLink)
        .join(FinancialReceiptCommentLink, FinancialReceiptCommentLink.comment_id == Comment.id)
        .filter(
            FinancialReceiptCommentLink.receipt_id == receipt_id,
            Comment.user_id == current_user.id,
        )
    )

    if payload.mode in {"keyword", "hybrid"}:
        pattern = f"%{payload.query}%"
        query = query.filter(
            or_(
                Comment.title.ilike(pattern),
                Comment.content.ilike(pattern),
                Comment.id.in_(matched_note_ids or [-1]),
            )
        )
        rows = query.order_by(FinancialReceiptCommentLink.created_at.desc()).limit(payload.limit).all()
    else:
        if not matched_note_ids:
            return []

        rows = (
            query
            .filter(Comment.id.in_(matched_note_ids))
            .order_by(FinancialReceiptCommentLink.created_at.desc())
            .limit(payload.limit)
            .all()
        )

    return [
        FinancialReceiptCommentOut(
            id=comment.id,
            user_id=comment.user_id,
            title=comment.title,
            type=comment.type,
            content=comment.content,
            created_at=comment.created_at,
            note=link.note,
            linked_at=link.created_at,
        )
        for comment, link in rows
    ]


