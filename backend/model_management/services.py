from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models import User

from .models import ManagedModel, ModelDocumentLink, ModelCommentLink


def is_admin(user: User) -> bool:
    return user.role == "admin"


def get_model_or_404(db: Session, model_id: int, current_user: User) -> ManagedModel:
    query = db.query(ManagedModel).filter(ManagedModel.id == model_id)
    if not is_admin(current_user):
        query = query.filter(ManagedModel.owner_id == current_user.id)
    model = query.first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


def get_doc_ids(db: Session, model_id: int) -> List[int]:
    rows = (
        db.query(ModelDocumentLink.document_id)
        .filter(ModelDocumentLink.model_id == model_id)
        .all()
    )
    return [row[0] for row in rows]


def get_comment_ids(db: Session, model_id: int) -> List[int]:
    rows = (
        db.query(ModelCommentLink.comment_id)
        .filter(ModelCommentLink.model_id == model_id)
        .all()
    )
    return [row[0] for row in rows]


def get_doc_ids_for_models(db: Session, model_ids: List[int]) -> List[int]:
    if not model_ids:
        return []

    rows = (
        db.query(ModelDocumentLink.document_id)
        .filter(ModelDocumentLink.model_id.in_(model_ids))
        .all()
    )
    return list({row[0] for row in rows})


def get_comment_ids_for_models(db: Session, model_ids: List[int]) -> List[int]:
    if not model_ids:
        return []

    rows = (
        db.query(ModelCommentLink.comment_id)
        .filter(ModelCommentLink.model_id.in_(model_ids))
        .all()
    )
    return list({row[0] for row in rows})
