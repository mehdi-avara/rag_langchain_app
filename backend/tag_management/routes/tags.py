from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from db.search_connector import (
    search_documents_text,
    search_document_part_hits_semantic,
    search_comments_text,
    search_comment_hits_semantic,
)
from deps import get_current_user
from Models import User, Document, CommentType
from schemas.search import (
    TextSearchRequest,
    ContentSearchResponse,
    TagSemanticSearchResponse,
    SemanticCommentSearchRequest,
    SemanticCommentSearchRequestWithId
)

from ..system_tag import SystemTag

from ..schemas import TagOut, TagCreate, TagUpdate
from ..services import (
    get_tag_or_404,
    validate_parent_tag,
    check_no_cycle,
    get_doc_ids,
    get_comment_ids,
    get_descendant_tag_ids,
    get_doc_ids_for_tags,
    get_comment_ids_for_tags,
    get_model_ids_for_tags,
    get_model_document_ids,
    get_tag_info_map,
    get_model_info_map,
    get_doc_to_tag_map,
    get_comment_to_tag_map,
    get_doc_to_model_map,
    get_tag_to_model_map,
)


router = APIRouter()


def _semantic_search_tag_scope(
    db: Session,
    current_user: User,
    query: str,
    tag_ids: list[int],
    top_k: int,
    types: list[CommentType],
):
    doc_ids = get_doc_ids_for_tags(db, tag_ids)
    comment_ids = get_comment_ids_for_tags(db, tag_ids)

    model_ids = get_model_ids_for_tags(db, tag_ids)
    model_doc_ids = get_model_document_ids(db, model_ids)

    all_doc_ids = list({*doc_ids, *model_doc_ids})

    document_hits = search_document_part_hits_semantic(
        db=db,
        query_text=query,
        owner_id=current_user.id,
        doc_ids=all_doc_ids,
        limit=top_k,
    )
    comment_hits = search_comment_hits_semantic(
        db=db,
        query_text=query,
        user_id=current_user.id,
        comment_ids=comment_ids,
        types=types or None,
        limit=top_k,
    )

    tag_map = get_tag_info_map(db, tag_ids)
    model_map = get_model_info_map(db, model_ids)
    doc_to_tag = get_doc_to_tag_map(db, tag_ids)
    comment_to_tag = get_comment_to_tag_map(db, tag_ids)
    doc_to_model = get_doc_to_model_map(db, model_ids)
    tag_to_model = get_tag_to_model_map(db, tag_ids)

    document_results = []
    for hit in document_hits:
        document_id = hit["document_id"]
        tag_id = doc_to_tag.get(document_id)
        model_id = doc_to_model.get(document_id)

        if tag_id is None and model_id is not None:
            for candidate_tag_id, candidate_model_id in tag_to_model.items():
                if candidate_model_id == model_id:
                    tag_id = candidate_tag_id
                    break

        tag = tag_map.get(tag_id) if tag_id is not None else None
        if tag is None:
            continue
        model = model_map.get(model_id) if model_id is not None else None

        document_results.append(
            {
                "tag_id": tag.id if tag else None,
                "tag_title": tag.tag_name if tag else None,
                "model_id": model.id if model else None,
                "model_title": model.model if model else None,
                **hit,
            }
        )

    comment_results = []
    for hit in comment_hits:
        comment_id = hit["comment_id"]
        tag_id = comment_to_tag.get(comment_id)
        tag = tag_map.get(tag_id) if tag_id is not None else None
        if tag is None:
            continue
        model_id = tag_to_model.get(tag_id) if tag_id is not None else None
        model = model_map.get(model_id) if model_id is not None else None

        comment_results.append(
            {
                "tag_id": tag.id if tag else None,
                "tag_title": tag.tag_name if tag else None,
                "model_id": model.id if model else None,
                "model_title": model.model if model else None,
                **hit,
            }
        )

    return {"documents": document_results, "comments": comment_results}


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
    doc_ids = get_doc_ids(db, tag_id)
    comment_ids = get_comment_ids(db, tag_id)

    return {
        "documents": search_documents_text(
            db=db,
            query_text=payload.query,
            owner_id=current_user.id,
            doc_ids=doc_ids,
            limit=payload.limit,
        ),
        "comments": search_comments_text(
            db=db,
            query_text=payload.query,
            user_id=current_user.id,
            comment_ids=comment_ids,
            limit=payload.limit,
        ),
    }


@router.post("/semantic-search", response_model=TagSemanticSearchResponse, status_code=status.HTTP_200_OK)
async def semantic_search_all_tags_content(
    payload: SemanticCommentSearchRequestWithId,
    top_k: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag_ids = [row[0] for row in db.query(SystemTag.id).filter(SystemTag.owner_id == current_user.id).all()]
    return _semantic_search_tag_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        tag_ids=tag_ids,
        top_k=top_k,
        types=payload.types,
    )


@router.post("/{tag_id}/semantic-search", response_model=TagSemanticSearchResponse, status_code=status.HTTP_200_OK)
async def semantic_search_tag_content(
    tag_id: int,
    payload: SemanticCommentSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)
    tag_ids = get_descendant_tag_ids(db, tag_id, current_user.id)

    return _semantic_search_tag_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        tag_ids=tag_ids,
        top_k=top_k,
        types=payload.types,
    )


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
