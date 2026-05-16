from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from db.init_db import get_db
from db.search_connector import (
    search_documents_text,
    search_document_part_hits_semantic,
    search_comments_text,
    search_comment_hits_semantic,
)
from deps import require_permission
from Models import User, CommentType, Comment
from routs.documents import _get_accessible_document_ids

from ..models import ManagedModel
from ..schemas import ModelCreate, ModelUpdate, ModelOut, ModelListOut
from ..services import (
    get_model_or_404,
    get_doc_ids,
    get_comment_ids,
    get_receipt_ids,
    get_doc_ids_for_models,
    get_comment_ids_for_models,
    get_model_info_map,
    get_doc_to_model_map,
    get_comment_to_model_map,
    require_company,
)
from schemas.search import (
    TextSearchRequest,
    ContentSearchResponse,
    ModelSemanticSearchResponse,
    SemanticCommentSearchRequest,
    SemanticCommentSearchRequestWithId,
)


router = APIRouter()


def _semantic_search_model_scope(
    db: Session,
    current_user: User,
    query: str,
    model_ids: list[int],
    doc_top_k: int,
    comment_top_k: int,
    types: list[CommentType],
):
    company_id = require_company(current_user)
    doc_ids = get_doc_ids_for_models(db, model_ids)
    comment_ids = get_comment_ids_for_models(db, model_ids)

    accessible_doc_ids = _get_accessible_document_ids(db, current_user, "read")
    if accessible_doc_ids is not None:
        accessible_set = set(accessible_doc_ids)
        doc_ids = [doc_id for doc_id in doc_ids if doc_id in accessible_set]

    owned_comment_ids = [
        row[0]
        for row in db.query(Comment.id)
        .filter(Comment.user_id == current_user.id)
        .all()
    ]
    owned_comment_set = set(owned_comment_ids)
    comment_ids = [comment_id for comment_id in comment_ids if comment_id in owned_comment_set]

    document_hits = []
    if doc_top_k > 0:
        document_hits = search_document_part_hits_semantic(
            db=db,
            query_text=query,
            doc_ids=doc_ids,
            limit=doc_top_k,
        )

    comment_hits = []
    if comment_top_k > 0:
        comment_hits = search_comment_hits_semantic(
            db=db,
            query_text=query,
            user_id=current_user.id,
            comment_ids=comment_ids,
            types=types or None,
            limit=comment_top_k,
        )

    model_map = get_model_info_map(db, model_ids, company_id)
    doc_to_model = get_doc_to_model_map(db, model_ids)
    comment_to_model = get_comment_to_model_map(db, model_ids)

    documents = []
    for hit in document_hits:
        model_id = doc_to_model.get(hit["document_id"])
        model = model_map.get(model_id) if model_id is not None else None
        documents.append(
            {
                "model_id": model.id if model else None,
                "model_title": model.model if model else None,
                **hit,
            }
        )

    comments = []
    for hit in comment_hits:
        model_id = comment_to_model.get(hit["comment_id"])
        model = model_map.get(model_id) if model_id is not None else None
        comments.append(
            {
                "model_id": model.id if model else None,
                "model_title": model.model if model else None,
                **hit,
            }
        )

    return {"documents": documents, "comments": comments}


def _model_out(db: Session, model: ManagedModel) -> ModelOut:
    return ModelOut(
        id=model.id,
        company_id=model.company_id,
        manufacturer=model.manufacturer,
        model=model.model,
        description=model.description,
        type=model.type,
        owner_id=model.owner_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        doc_ids=get_doc_ids(db, model.id),
        comment_ids=get_comment_ids(db, model.id),
        receipt_ids=get_receipt_ids(db, model.id),
    )


@router.post("/", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: ModelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:create")),
):
    company_id = require_company(current_user)
    existing = (
        db.query(ManagedModel)
        .filter(
            ManagedModel.company_id == company_id,
            ManagedModel.manufacturer == payload.manufacturer,
            ManagedModel.model == payload.model,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Model already exists")

    new_model = ManagedModel(
        company_id=company_id,
        manufacturer=payload.manufacturer,
        model=payload.model,
        description=payload.description,
        type=payload.type,
        owner_id=current_user.id,
    )
    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    return _model_out(db, new_model)


@router.get("/", response_model=List[ModelListOut])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:read")),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    company_id = require_company(current_user)
    query = db.query(ManagedModel).filter(ManagedModel.company_id == company_id)

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

    models = (
        query
        .order_by(ManagedModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return models


@router.get("/{model_id}", response_model=ModelOut)
def get_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:read")),
):
    model = get_model_or_404(db, model_id, current_user)
    return _model_out(db, model)


@router.post(
    "/{model_id}/filter",
    response_model=ContentSearchResponse,
    status_code=status.HTTP_200_OK,
)
def filter_model_content(
    model_id: int,
    payload: TextSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:search")),
):
    model = get_model_or_404(db, model_id, current_user)
    doc_ids = get_doc_ids(db, model.id)
    comment_ids = get_comment_ids(db, model.id)

    accessible_doc_ids = _get_accessible_document_ids(db, current_user, "read")
    if accessible_doc_ids is not None:
        accessible_set = set(accessible_doc_ids)
        doc_ids = [doc_id for doc_id in doc_ids if doc_id in accessible_set]

    owned_comment_ids = [
        row[0]
        for row in db.query(Comment.id)
        .filter(Comment.user_id == current_user.id)
        .all()
    ]
    owned_comment_set = set(owned_comment_ids)
    comment_ids = [comment_id for comment_id in comment_ids if comment_id in owned_comment_set]

    return {
        "documents": search_documents_text(
            db=db,
            query_text=payload.query,
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


@router.post(
    "/semantic-search",
    response_model=ModelSemanticSearchResponse,
    status_code=status.HTTP_200_OK,
)
def semantic_search_all_models_content(
    payload: SemanticCommentSearchRequestWithId,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:search")),
):
    company_id = require_company(current_user)
    model_ids = [
        row[0]
        for row in (
            db.query(ManagedModel.id)
            .filter(ManagedModel.company_id == company_id)
            .all()
        )
    ]

    return _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        model_ids=model_ids,
        doc_top_k=top_k,
        comment_top_k=top_k,
        types=payload.types,
    )


@router.post(
    "/{model_id}/semantic-search",
    response_model=ModelSemanticSearchResponse,
    status_code=status.HTTP_200_OK,
)
def semantic_search_model_content(
    model_id: int,
    payload: SemanticCommentSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:search")),
):
    model = get_model_or_404(db, model_id, current_user)

    return _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        model_ids=[model.id],
        doc_top_k=top_k,
        comment_top_k=top_k,
        types=payload.types,
    )


@router.patch("/{model_id}", response_model=ModelOut)
def update_model(
    model_id: int,
    payload: ModelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:update")),
):
    model = get_model_or_404(db, model_id, current_user)

    if payload.manufacturer is not None:
        model.manufacturer = payload.manufacturer
    if payload.model is not None:
        model.model = payload.model
    if payload.description is not None:
        model.description = payload.description
    if payload.type is not None:
        model.type = payload.type

    if payload.manufacturer is not None or payload.model is not None:
        duplicate = (
            db.query(ManagedModel)
            .filter(
                ManagedModel.company_id == model.company_id,
                ManagedModel.manufacturer == model.manufacturer,
                ManagedModel.model == model.model,
                ManagedModel.id != model.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Model already exists")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Model already exists")

    db.refresh(model)
    return _model_out(db, model)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:delete")),
):
    model = get_model_or_404(db, model_id, current_user)
    db.delete(model)
    db.commit()
    return None
