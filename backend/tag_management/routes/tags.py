from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import User, SystemTag, Document

from ..schemas import TagOut, TagCreate, TagUpdate
from ..services import get_tag_or_404, validate_parent_tag, check_no_cycle


router = APIRouter()


@router.get("/system_tags", response_model=List[TagOut], status_code=status.HTTP_200_OK)
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    root_only: bool = Query(False, description="If true, only return root tags"),
):
    query = db.query(SystemTag).filter(SystemTag.owner_id == current_user.id)
    if root_only:
        query = query.filter(SystemTag.father_tag_id.is_(None))

    return query.order_by(SystemTag.created_at).all()


@router.get("/system_tags/{tag_id}", response_model=TagOut, status_code=status.HTTP_200_OK)
async def get_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag = get_tag_or_404(db, tag_id, current_user.id)
    return tag


@router.post("/system_tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    payload: TagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = validate_parent_tag(db, payload.father_tag_id, current_user.id)

    tag = SystemTag(
        owner_id=current_user.id,
        father_tag_id=payload.father_tag_id,
        tag_name=payload.tag_name,
        description=payload.description,
    )

    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.put("/system_tags/{tag_id}", response_model=TagOut, status_code=status.HTTP_200_OK)
async def update_tag(
    tag_id: int,
    payload: TagUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag = get_tag_or_404(db, tag_id, current_user.id)

    if payload.father_tag_id is not None or payload.father_tag_id is None:
        new_parent_id = payload.father_tag_id
        if new_parent_id != tag.father_tag_id:
            if new_parent_id is not None:
                validate_parent_tag(db, new_parent_id, current_user.id)
            check_no_cycle(db, tag, new_parent_id, current_user.id)
            tag.father_tag_id = new_parent_id

    if payload.tag_name is not None:
        tag.tag_name = payload.tag_name

    if payload.description is not None:
        tag.description = payload.description

    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/system_tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag = get_tag_or_404(db, tag_id, current_user.id)

    docs = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id, Document.system_tag_id == tag.id)
        .all()
    )
    for doc in docs:
        doc.system_tag_id = None

    db.delete(tag)
    db.commit()
    return None


@router.get("/system_tags/{tag_id}/children", response_model=List[TagOut], status_code=status.HTTP_200_OK)
async def list_child_tags(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parent = get_tag_or_404(db, tag_id, current_user.id)
    return sorted(parent.children, key=lambda t: t.created_at)
