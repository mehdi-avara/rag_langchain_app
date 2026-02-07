from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from db.base import Base


class ManagedModel(Base):
    __tablename__ = "managed_models"
    __table_args__ = (
        UniqueConstraint("manufacturer", "model"),
    )

    id = Column(Integer, primary_key=True)
    manufacturer = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User")
    document_links = relationship(
        "ModelDocumentLink",
        back_populates="model",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    comment_links = relationship(
        "ModelCommentLink",
        back_populates="model",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModelDocumentLink(Base):
    __tablename__ = "model_document_links"
    __table_args__ = (
        Index("ix_model_document_links_model_id", "model_id"),
        Index("ix_model_document_links_document_id", "document_id"),
    )

    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="CASCADE"), primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    model = relationship("ManagedModel", back_populates="document_links")
    document = relationship("Document")
    linked_by = relationship("User")


class ModelCommentLink(Base):
    __tablename__ = "model_comment_links"
    __table_args__ = (
        Index("ix_model_comment_links_model_id", "model_id"),
        Index("ix_model_comment_links_comment_id", "comment_id"),
    )

    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="CASCADE"), primary_key=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    model = relationship("ManagedModel", back_populates="comment_links")
    comment = relationship("Comment")
    linked_by = relationship("User")
