from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from db.init_db import get_db
from deps import get_current_user
from Models import User, Document, Comment
from core.agents import build_answer_graph, GraphState

from .models import ManagedModel, ModelDocumentLink, ModelCommentLink
from .schemas import (
    ModelCreate,
    ModelUpdate,
    ModelOut,
    ModelListOut,
    ModelDocLinkCreate,
    ModelCommentLinkCreate,
    ModelDocLinkOut,
    ModelCommentLinkOut,
    ModelDocumentOut,
    ModelCommentOut,
    ModelAskRequest,
    ModelAskResponse,
)


router = APIRouter( tags=["models"])


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _get_model_or_404(db: Session, model_id: int, current_user: User) -> ManagedModel:
    query = db.query(ManagedModel).filter(ManagedModel.id == model_id)
    if not _is_admin(current_user):
        query = query.filter(ManagedModel.owner_id == current_user.id)
    model = query.first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


def _get_doc_ids(db: Session, model_id: int) -> List[int]:
    rows = (
        db.query(ModelDocumentLink.document_id)
        .filter(ModelDocumentLink.model_id == model_id)
        .all()
    )
    return [row[0] for row in rows]


def _get_comment_ids(db: Session, model_id: int) -> List[int]:
    rows = (
        db.query(ModelCommentLink.comment_id)
        .filter(ModelCommentLink.model_id == model_id)
        .all()
    )
    return [row[0] for row in rows]


@router.post("", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
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


@router.get("", response_model=List[ModelListOut])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(ManagedModel)
    if not _is_admin(current_user):
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
    model = _get_model_or_404(db, model_id, current_user)
    doc_ids = _get_doc_ids(db, model.id)
    comment_ids = _get_comment_ids(db, model.id)

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


@router.patch("/{model_id}", response_model=ModelOut)
def update_model(
    model_id: int,
    payload: ModelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = _get_model_or_404(db, model_id, current_user)

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

    doc_ids = _get_doc_ids(db, model.id)
    comment_ids = _get_comment_ids(db, model.id)

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
    model = _get_model_or_404(db, model_id, current_user)
    db.delete(model)
    db.commit()
    return None


@router.post("/{model_id}/documents", response_model=ModelDocLinkOut)
def link_document(
    model_id: int,
    payload: ModelDocLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = _get_model_or_404(db, model_id, current_user)

    doc = db.query(Document).filter(Document.id == payload.document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _is_admin(current_user) and doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to link this document")

    link = (
        db.query(ModelDocumentLink)
        .filter(
            ModelDocumentLink.model_id == model.id,
            ModelDocumentLink.document_id == doc.id,
        )
        .first()
    )
    if link:
        return link

    link = ModelDocumentLink(
        model_id=model.id,
        document_id=doc.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/{model_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_document(
    model_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_model_or_404(db, model_id, current_user)

    link = (
        db.query(ModelDocumentLink)
        .filter(
            ModelDocumentLink.model_id == model_id,
            ModelDocumentLink.document_id == document_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/{model_id}/documents", response_model=List[ModelDocumentOut])
def list_linked_documents(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    # system_tag_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = _get_model_or_404(db, model_id, current_user)

    query = (
        db.query(Document, ModelDocumentLink)
        .join(ModelDocumentLink, ModelDocumentLink.document_id == Document.id)
        .filter(ModelDocumentLink.model_id == model_id)
    )

    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))
    if status_filter:
        query = query.filter(Document.status == status_filter)
    # if system_tag_id:
    #     query = query.filter(Document.system_tag_id == system_tag_id)

    rows = (
        query
        .order_by(ModelDocumentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[ModelDocumentOut] = []
    for doc, link in rows:
        results.append(
            ModelDocumentOut(
                id=doc.id,
                filename=doc.filename,
                # system_tag_id=doc.system_tag_id,
                n_pages=doc.n_pages,
                n_chunks=doc.n_chunks,
                created_at=doc.created_at,
                status=doc.status,
                abstract=doc.abstract,
                file_path=doc.file_path,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results


@router.post("/{model_id}/comments", response_model=ModelCommentLinkOut)
def link_comment(
    model_id: int,
    payload: ModelCommentLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = _get_model_or_404(db, model_id, current_user)

    comment = db.query(Comment).filter(Comment.id == payload.comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if not _is_admin(current_user) and comment.user_id != current_user.id:
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
    _ = _get_model_or_404(db, model_id, current_user)

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
    _ = _get_model_or_404(db, model_id, current_user)

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
                doc_id=comment.doc_id,
                chunk_id=comment.chunk_id,
                type=comment.type,
                content=comment.content,
                created_at=comment.created_at,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results


@router.post("/{model_id}/ask", response_model=ModelAskResponse)
async def ask_model(
    model_id: int,
    payload: ModelAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = _get_model_or_404(db, model_id, current_user)

    doc_ids = _get_doc_ids(db, model.id)
    comment_ids = _get_comment_ids(db, model.id)

    if payload.scope == "docs":
        comment_ids = []
    elif payload.scope == "comments":
        doc_ids = None

    state: GraphState = {
        "question": payload.question,
        "route": payload.route,
        "db": db,
        "mode": payload.mode,
        "doc_ids": doc_ids,
        "comment_ids": comment_ids,
        "scope": payload.scope,
    }

    graph = build_answer_graph()
    result = await graph.ainvoke(state)

    chunks = result.get("chunks", [])
    comments = result.get("comments", [])
    chunk_ids = [c.id for c in chunks]
    comment_ids_used = [c.id for c in comments]

    return ModelAskResponse(
        answer=result.get("answer", ""),
        citations=chunk_ids,
        used_chunk_ids=chunk_ids,
        used_comment_ids=comment_ids_used,
    )
