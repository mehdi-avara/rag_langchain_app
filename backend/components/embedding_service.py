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

    if config.model_name != model_name:
        config.model_name = model_name
        config.base_url = base_url
        config.api_key = api_key
        reset_all_embeddings(db)
        db.commit()
        db.refresh(config)

    return config


def reset_all_embeddings(db: Session) -> None:
    db.query(Chunk).update({Chunk.embedding: None}, synchronize_session=False)
    db.query(Comment).update({Comment.embedding: None}, synchronize_session=False)
    db.query(FinancialReceipt).update({FinancialReceipt.description_embedding: None}, synchronize_session=False)
    db.query(FinancialReceiptCommentLink).update({FinancialReceiptCommentLink.note_embedding: None}, synchronize_session=False)
    db.query(ModelCommentLink).update({ModelCommentLink.note_embedding: None}, synchronize_session=False)
    db.query(ModelReceiptLink).update({ModelReceiptLink.note_embedding: None}, synchronize_session=False)
    db.query(TagCommentLink).update({TagCommentLink.note_embedding: None}, synchronize_session=False)
    db.query(TagReceiptLink).update({TagReceiptLink.note_embedding: None}, synchronize_session=False)


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
