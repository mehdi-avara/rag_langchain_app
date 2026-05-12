from typing import List

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from components import generate_embeddings_for_chunks
from Models import User

from .models import ManagedModel, ModelDocumentLink, ModelCommentLink, ModelReceiptLink


def require_company(current_user: User) -> int:
    if current_user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")
    return current_user.company_id


def get_model_or_404(db: Session, model_id: int, current_user: User) -> ManagedModel:
    company_id = require_company(current_user)
    model = (
        db.query(ManagedModel)
        .filter(
            ManagedModel.id == model_id,
            ManagedModel.company_id == company_id,
        )
        .first()
    )
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


def get_receipt_ids(db: Session, model_id: int) -> List[int]:
    rows = (
        db.query(ModelReceiptLink.receipt_id)
        .filter(ModelReceiptLink.model_id == model_id)
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


def safe_embed_link_note(text_value: str | None) -> list[float] | None:
    if not text_value:
        return None
    try:
        embeddings = generate_embeddings_for_chunks([text_value])
    except Exception:
        return None
    return embeddings[0] if embeddings else None


def search_model_receipt_link_ids(
    db: Session,
    model_id: int,
    query_text: str,
    mode: str,
    limit: int,
) -> list[int]:
    matched_ids: list[int] = []
    if mode in {"keyword", "hybrid"}:
        pattern = f"%{query_text}%"
        rows = (
            db.query(ModelReceiptLink.receipt_id)
            .filter(
                ModelReceiptLink.model_id == model_id,
                ModelReceiptLink.note.ilike(pattern),
            )
            .limit(limit)
            .all()
        )
        matched_ids.extend([row[0] for row in rows])

    if mode in {"vector", "hybrid"}:
        query_embedding = safe_embed_link_note(query_text)
        if query_embedding is not None:
            embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
            rows = db.execute(
                text(
                    """
                    SELECT receipt_id
                    FROM model_receipt_links
                    WHERE model_id = :model_id
                      AND note_embedding IS NOT NULL
                    ORDER BY (1 - (note_embedding <=> (:query_vec)::vector)) DESC
                    LIMIT :limit
                    """
                ),
                {
                    "model_id": model_id,
                    "query_vec": embedding_str,
                    "limit": limit,
                },
            ).fetchall()
            matched_ids.extend([row.receipt_id for row in rows])

    seen: set[int] = set()
    output: list[int] = []
    for receipt_id in matched_ids:
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        output.append(receipt_id)
    return output[:limit]


def get_model_info_map(db: Session, model_ids: List[int], company_id: int) -> dict[int, ManagedModel]:
    if not model_ids:
        return {}
    models = (
        db.query(ManagedModel)
        .filter(
            ManagedModel.id.in_(model_ids),
            ManagedModel.company_id == company_id,
        )
        .all()
    )
    return {model.id: model for model in models}


def get_doc_to_model_map(db: Session, model_ids: List[int]) -> dict[int, int]:
    if not model_ids:
        return {}

    rows = (
        db.query(ModelDocumentLink.document_id, ModelDocumentLink.model_id)
        .filter(ModelDocumentLink.model_id.in_(model_ids))
        .all()
    )
    mapping: dict[int, int] = {}
    for document_id, model_id in rows:
        mapping.setdefault(document_id, model_id)
    return mapping


def get_comment_to_model_map(db: Session, model_ids: List[int]) -> dict[int, int]:
    if not model_ids:
        return {}

    rows = (
        db.query(ModelCommentLink.comment_id, ModelCommentLink.model_id)
        .filter(ModelCommentLink.model_id.in_(model_ids))
        .all()
    )
    mapping: dict[int, int] = {}
    for comment_id, model_id in rows:
        mapping.setdefault(comment_id, model_id)
    return mapping
