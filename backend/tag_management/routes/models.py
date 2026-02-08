from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from db.init_db import get_db
from deps import get_current_user
from Models import User

from model_management.models import ManagedModel

from ..models import TagModelLink
from ..schemas import TagModelLinkCreate, TagModelLinkOut, TagModelOut
from ..services import get_tag_or_404, is_admin


router = APIRouter()


@router.post("/system_tags/{tag_id}/models", response_model=TagModelLinkOut)
def link_model(
    tag_id: int,
    payload: TagModelLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    model = db.query(ManagedModel).filter(ManagedModel.id == payload.model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not is_admin(current_user) and model.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to link this model")

    link = (
        db.query(TagModelLink)
        .filter(
            TagModelLink.tag_id == tag_id,
            TagModelLink.model_id == model.id,
        )
        .first()
    )
    if link:
        return link

    link = TagModelLink(
        tag_id=tag_id,
        model_id=model.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/system_tags/{tag_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_model(
    tag_id: int,
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    link = (
        db.query(TagModelLink)
        .filter(
            TagModelLink.tag_id == tag_id,
            TagModelLink.model_id == model_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/system_tags/{tag_id}/models", response_model=List[TagModelOut])
def list_tag_models(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    query = (
        db.query(ManagedModel, TagModelLink)
        .join(TagModelLink, TagModelLink.model_id == ManagedModel.id)
        .filter(TagModelLink.tag_id == tag_id)
    )

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                ManagedModel.manufacturer.ilike(pattern),
                ManagedModel.model.ilike(pattern),
            )
        )
    if type:
        query = query.filter(ManagedModel.type == type)

    rows = (
        query
        .order_by(TagModelLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[TagModelOut] = []
    for model, link in rows:
        results.append(
            TagModelOut(
                id=model.id,
                manufacturer=model.manufacturer,
                model=model.model,
                description=model.description,
                type=model.type,
                owner_id=model.owner_id,
                created_at=model.created_at,
                updated_at=model.updated_at,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results
