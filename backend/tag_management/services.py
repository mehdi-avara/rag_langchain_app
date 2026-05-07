from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from components import generate_embeddings_for_chunks
from Models import User

from .system_tag import SystemTag
from .models import TagDocumentLink, TagCommentLink, TagModelLink, TagReceiptLink
from model_management.models import ManagedModel, ModelDocumentLink


def is_admin(user: User) -> bool:
    return user.role == "admin"


def get_tag_or_404(db: Session, tag_id: int, user_id: int) -> SystemTag:
    tag = (
        db.query(SystemTag)
        .filter(SystemTag.id == tag_id, SystemTag.owner_id == user_id)
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="System tag not found")
    return tag


def validate_parent_tag(db: Session, parent_id: int | None, user_id: int) -> SystemTag | None:
    if parent_id is None:
        return None

    parent = (
        db.query(SystemTag)
        .filter(SystemTag.id == parent_id, SystemTag.owner_id == user_id)
        .first()
    )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent tag not found")
    return parent


def check_no_cycle(db: Session, tag: SystemTag, new_parent_id: int | None, user_id: int) -> None:
    if new_parent_id is None:
        return

    if new_parent_id == tag.id:
        raise HTTPException(status_code=400, detail="A tag cannot be its own parent")

    current = (
        db.query(SystemTag)
        .filter(SystemTag.id == new_parent_id, SystemTag.owner_id == user_id)
        .first()
    )
    while current is not None:
        if current.id == tag.id:
            raise HTTPException(
                status_code=400,
                detail="Cannot set a descendant as parent (cycle detected)",
            )
        if current.father_tag_id is None:
            break
        current = (
            db.query(SystemTag)
            .filter(SystemTag.id == current.father_tag_id, SystemTag.owner_id == user_id)
            .first()
        )


def get_doc_ids(db: Session, tag_id: int) -> list[int]:
    rows = (
        db.query(TagDocumentLink.document_id)
        .filter(TagDocumentLink.tag_id == tag_id)
        .all()
    )
    return [row[0] for row in rows]


def get_comment_ids(db: Session, tag_id: int) -> list[int]:
    rows = (
        db.query(TagCommentLink.comment_id)
        .filter(TagCommentLink.tag_id == tag_id)
        .all()
    )
    return [row[0] for row in rows]


def get_receipt_ids(db: Session, tag_id: int) -> list[int]:
    rows = (
        db.query(TagReceiptLink.receipt_id)
        .filter(TagReceiptLink.tag_id == tag_id)
        .all()
    )
    return [row[0] for row in rows]


def get_doc_ids_for_tags(db: Session, tag_ids: list[int]) -> list[int]:
    if not tag_ids:
        return []

    rows = (
        db.query(TagDocumentLink.document_id)
        .filter(TagDocumentLink.tag_id.in_(tag_ids))
        .all()
    )
    return list({row[0] for row in rows})


def get_comment_ids_for_tags(db: Session, tag_ids: list[int]) -> list[int]:
    if not tag_ids:
        return []

    rows = (
        db.query(TagCommentLink.comment_id)
        .filter(TagCommentLink.tag_id.in_(tag_ids))
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


def search_tag_receipt_link_ids(
    db: Session,
    tag_id: int,
    query_text: str,
    mode: str,
    limit: int,
) -> list[int]:
    matched_ids: list[int] = []
    if mode in {"keyword", "hybrid"}:
        pattern = f"%{query_text}%"
        rows = (
            db.query(TagReceiptLink.receipt_id)
            .filter(
                TagReceiptLink.tag_id == tag_id,
                TagReceiptLink.note.ilike(pattern),
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
                    FROM tag_receipt_links
                    WHERE tag_id = :tag_id
                      AND note_embedding IS NOT NULL
                    ORDER BY (1 - (note_embedding <=> (:query_vec)::vector)) DESC
                    LIMIT :limit
                    """
                ),
                {
                    "tag_id": tag_id,
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


def get_descendant_tag_ids(db: Session, root_tag_id: int, user_id: int) -> list[int]:
    tag_ids: list[int] = []
    stack = [root_tag_id]

    while stack:
        current_id = stack.pop()
        if current_id in tag_ids:
            continue
        tag_ids.append(current_id)

        children = (
            db.query(SystemTag.id)
            .filter(SystemTag.father_tag_id == current_id, SystemTag.owner_id == user_id)
            .all()
        )
        stack.extend([row[0] for row in children])

    return tag_ids


def get_model_ids_for_tags(db: Session, tag_ids: list[int]) -> list[int]:
    if not tag_ids:
        return []

    rows = (
        db.query(TagModelLink.model_id)
        .filter(TagModelLink.tag_id.in_(tag_ids))
        .all()
    )
    return list({row[0] for row in rows})


def get_model_document_ids(db: Session, model_ids: list[int]) -> list[int]:
    if not model_ids:
        return []

    rows = (
        db.query(ModelDocumentLink.document_id)
        .filter(ModelDocumentLink.model_id.in_(model_ids))
        .all()
    )
    return list({row[0] for row in rows})


def get_tag_info_map(db: Session, tag_ids: list[int]) -> dict[int, SystemTag]:
    if not tag_ids:
        return {}
    tags = db.query(SystemTag).filter(SystemTag.id.in_(tag_ids)).all()
    return {tag.id: tag for tag in tags}


def get_model_info_map(db: Session, model_ids: list[int]) -> dict[int, ManagedModel]:
    if not model_ids:
        return {}
    models = db.query(ManagedModel).filter(ManagedModel.id.in_(model_ids)).all()
    return {model.id: model for model in models}


def get_doc_to_tag_map(db: Session, tag_ids: list[int]) -> dict[int, int]:
    if not tag_ids:
        return {}
    rows = (
        db.query(TagDocumentLink.document_id, TagDocumentLink.tag_id)
        .filter(TagDocumentLink.tag_id.in_(tag_ids))
        .all()
    )
    mapping: dict[int, int] = {}
    for document_id, tag_id in rows:
        mapping.setdefault(document_id, tag_id)
    return mapping


def get_comment_to_tag_map(db: Session, tag_ids: list[int]) -> dict[int, int]:
    if not tag_ids:
        return {}
    rows = (
        db.query(TagCommentLink.comment_id, TagCommentLink.tag_id)
        .filter(TagCommentLink.tag_id.in_(tag_ids))
        .all()
    )
    mapping: dict[int, int] = {}
    for comment_id, tag_id in rows:
        mapping.setdefault(comment_id, tag_id)
    return mapping


def get_doc_to_model_map(db: Session, model_ids: list[int]) -> dict[int, int]:
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


def get_tag_to_model_map(db: Session, tag_ids: list[int]) -> dict[int, int]:
    if not tag_ids:
        return {}
    rows = (
        db.query(TagModelLink.tag_id, TagModelLink.model_id)
        .filter(TagModelLink.tag_id.in_(tag_ids))
        .all()
    )
    mapping: dict[int, int] = {}
    for tag_id, model_id in rows:
        mapping.setdefault(tag_id, model_id)
    return mapping
