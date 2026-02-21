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
from deps import get_current_user
from Models import User, CommentType

from ..models import ManagedModel
from ..schemas import ModelCreate, ModelUpdate, ModelOut, ModelListOut
from ..services import (
    get_model_or_404,
    get_doc_ids,
    get_comment_ids,
    is_admin,
    get_doc_ids_for_models,
    get_comment_ids_for_models,
    get_model_info_map,
    get_doc_to_model_map,
    get_comment_to_model_map,
)
from schemas.search import (
    TextSearchRequest,
    ContentSearchResponse,
    ModelSemanticSearchResponse,
    SemanticCommentSearchRequest,
)


router = APIRouter()


def _semantic_search_model_scope(
    db: Session,
    current_user: User,
    query: str,
    model_ids: list[int],
    top_k: int,
    types: list[CommentType],
):
    doc_ids = get_doc_ids_for_models(db, model_ids)
    comment_ids = get_comment_ids_for_models(db, model_ids)

    document_hits = search_document_part_hits_semantic(
        db=db,
        query_text=query,
        owner_id=current_user.id,
        doc_ids=doc_ids,
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

    model_map = get_model_info_map(db, model_ids)
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


@router.post("/", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def create_model(
    payload: ModelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = (
        db.query(ManagedModel)
        .filter(
            ManagedModel.manufacturer == payload.manufacturer,
            ManagedModel.model == payload.model,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Model already exists")

    new_model = ManagedModel(
        manufacturer=payload.manufacturer,
        model=payload.model,
        description=payload.description,
        type=payload.type,
        owner_id=current_user.id,
    )
    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    return ModelOut(
        id=new_model.id,
        manufacturer=new_model.manufacturer,
        model=new_model.model,
        description=new_model.description,
        type=new_model.type,
        owner_id=new_model.owner_id,
        created_at=new_model.created_at,
        updated_at=new_model.updated_at,
        doc_ids=[],
        comment_ids=[],
    )


@router.get("/", response_model=List[ModelListOut])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(ManagedModel)
    if not is_admin(current_user):
        query = query.filter(ManagedModel.owner_id == current_user.id)

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
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)
    doc_ids = get_doc_ids(db, model.id)
    comment_ids = get_comment_ids(db, model.id)

    return ModelOut(
        id=model.id,
        manufacturer=model.manufacturer,
        model=model.model,
        description=model.description,
        type=model.type,
        owner_id=model.owner_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        doc_ids=doc_ids,
        comment_ids=comment_ids,
    )


@router.post(
    "/{model_id}/filter",
    response_model=ContentSearchResponse,
    status_code=status.HTTP_200_OK,
)
def filter_model_content(
    model_id: int,
    payload: TextSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)
    doc_ids = get_doc_ids(db, model.id)
    comment_ids = get_comment_ids(db, model.id)

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


@router.post(
    "/semantic-search",
    response_model=ModelSemanticSearchResponse,
    status_code=status.HTTP_200_OK,
)
def semantic_search_all_models_content(
    payload: SemanticCommentSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ManagedModel.id)
    if not is_admin(current_user):
        query = query.filter(ManagedModel.owner_id == current_user.id)
    model_ids = [row[0] for row in query.all()]

    return _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        model_ids=model_ids,
        top_k=top_k,
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
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)

    return _semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query=payload.query,
        model_ids=[model.id],
        top_k=top_k,
        types=payload.types,
    )


@router.patch("/{model_id}", response_model=ModelOut)
def update_model(
    model_id: int,
    payload: ModelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    doc_ids = get_doc_ids(db, model.id)
    comment_ids = get_comment_ids(db, model.id)

    return ModelOut(
        id=model.id,
        manufacturer=model.manufacturer,
        model=model.model,
        description=model.description,
        type=model.type,
        owner_id=model.owner_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        doc_ids=doc_ids,
        comment_ids=comment_ids,
    )


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = get_model_or_404(db, model_id, current_user)
    db.delete(model)
    db.commit()
    return None
