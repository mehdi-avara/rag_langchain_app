from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from db.search_connector import (
    search_documents_text,
    search_documents_semantic,
    search_comments_text,
    search_comments_semantic,
)
from deps import get_current_user
from Models import User, Document
from schemas.search import TextSearchRequest, SemanticSearchRequest, ContentSearchResponse

from ..system_tag import SystemTag

from ..schemas import TagOut, TagCreate, TagUpdate
from ..services import (
    get_tag_or_404,
    validate_parent_tag,
    check_no_cycle,
    get_doc_ids_for_tags,
    get_comment_ids_for_tags,
    get_descendant_tag_ids,
)


router = APIRouter()


@router.get("/", response_model=List[TagOut], status_code=status.HTTP_200_OK)
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    root_only: bool = Query(False, description="If true, only return root tags"),
):
    query = db.query(SystemTag).filter(SystemTag.owner_id == current_user.id)
    if root_only:
        query = query.filter(SystemTag.father_tag_id.is_(None))

    return query.order_by(SystemTag.created_at).all()


@router.get("/{tag_id}", response_model=TagOut, status_code=status.HTTP_200_OK)
async def get_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag = get_tag_or_404(db, tag_id, current_user.id)
    return tag


@router.post("/{tag_id}/filter", response_model=ContentSearchResponse, status_code=status.HTTP_200_OK)
async def filter_tag_content(
    tag_id: int,
    payload: TextSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)
    tag_ids = get_descendant_tag_ids(db, tag_id, current_user.id)
    doc_ids = get_doc_ids_for_tags(db, tag_ids)
    comment_ids = get_comment_ids_for_tags(db, tag_ids)

    return {
        "documents": search_documents_text(
            db=db,
            query_text=payload.query,
            owner_id=current_user.id,
            doc_ids=doc_ids,
            limit=payload.limit,
            tag_scope_ids=tag_ids,
        ),
        "comments": search_comments_text(
            db=db,
            query_text=payload.query,
            user_id=current_user.id,
            comment_ids=comment_ids,
            limit=payload.limit,
            tag_scope_ids=tag_ids,
        ),
    }


@router.post("/{tag_id}/semantic-search", response_model=ContentSearchResponse, status_code=status.HTTP_200_OK)
async def semantic_search_tag_content(
    tag_id: int,
    payload: SemanticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)
    tag_ids = get_descendant_tag_ids(db, tag_id, current_user.id)
    doc_ids = get_doc_ids_for_tags(db, tag_ids)
    comment_ids = get_comment_ids_for_tags(db, tag_ids)

    return {
        "documents": search_documents_semantic(
            db=db,
            query_text=payload.query,
            owner_id=current_user.id,
            doc_ids=doc_ids,
            limit=payload.limit,
            tag_scope_ids=tag_ids,
        ),
        "comments": search_comments_semantic(
            db=db,
            query_text=payload.query,
            user_id=current_user.id,
            comment_ids=comment_ids,
            limit=payload.limit,
            comment_type=payload.type,
            tag_scope_ids=tag_ids,
        ),
    }


@router.post("/", response_model=TagOut, status_code=status.HTTP_201_CREATED)
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


@router.put("/{tag_id}", response_model=TagOut, status_code=status.HTTP_200_OK)
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


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/{tag_id}/children", response_model=List[TagOut], status_code=status.HTTP_200_OK)
async def list_child_tags(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parent = get_tag_or_404(db, tag_id, current_user.id)
    return sorted(parent.children, key=lambda t: t.created_at)
