from __future__ import annotations

from sqlalchemy.orm import Session

from Models import Chunk, Comment
from Models.embedding_config import EmbeddingConfig
from financial_management.models import FinancialReceipt, FinancialReceiptCommentLink
from model_management.models import ModelCommentLink, ModelReceiptLink
from tag_management.models import TagCommentLink, TagReceiptLink


def get_or_create_embedding_config(db: Session, model_name: str, base_url: str, api_key: str) -> EmbeddingConfig:
    config = db.query(EmbeddingConfig).order_by(EmbeddingConfig.id.desc()).first()
    if config is None:
        config = EmbeddingConfig(model_name=model_name, base_url=base_url, api_key=api_key)
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    if config.model_name != model_name or config.base_url != base_url or config.api_key != api_key:
        config.model_name = model_name
        config.base_url = base_url
        config.api_key = api_key
        reset_all_embeddings(db)
        db.commit()
        db.refresh(config)

    return config


def _reset_model_embedding_fields(db: Session, model, field_names: list[str]) -> None:
    values = {}

    for field_name in field_names:
        if hasattr(model, field_name):
            values[getattr(model, field_name)] = None

    if values:
        db.query(model).update(values, synchronize_session=False)


def reset_all_embeddings(db: Session) -> None:
    _reset_model_embedding_fields(db, Chunk, ["embedding"])
    _reset_model_embedding_fields(db, Comment, ["embedding"])
    _reset_model_embedding_fields(db, FinancialReceipt, ["description_embedding"])
    _reset_model_embedding_fields(db, FinancialReceiptCommentLink, ["note_embedding", "embedding"])
    _reset_model_embedding_fields(db, ModelCommentLink, ["note_embedding", "embedding"])
    _reset_model_embedding_fields(db, ModelReceiptLink, ["note_embedding", "embedding"])
    _reset_model_embedding_fields(db, TagCommentLink, ["note_embedding", "embedding"])
    _reset_model_embedding_fields(db, TagReceiptLink, ["note_embedding", "embedding"])


def regenerate_missing_embeddings(db: Session, embed_func) -> int:
    updated = 0

    for comment in db.query(Comment).filter(Comment.embedding.is_(None)).all():
        vec = embed_func(comment.content)
        if vec is not None:
            comment.embedding = vec
            updated += 1

    for receipt in db.query(FinancialReceipt).filter(FinancialReceipt.description_embedding.is_(None)).all():
        vec = embed_func(receipt.description)
        if vec is not None:
            receipt.description_embedding = vec
            updated += 1

    db.commit()
    return updated
