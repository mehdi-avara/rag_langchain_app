from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from db.base import Base


class UserDocumentAccess(Base):
    __tablename__ = "user_document_access"
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", name="uq_user_document_access_user_document"),
        Index("ix_user_document_access_user_id", "user_id"),
        Index("ix_user_document_access_document_id", "document_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    can_read = Column(Boolean, nullable=False, default=True)
    can_download = Column(Boolean, nullable=False, default=False)
    can_ask = Column(Boolean, nullable=False, default=True)
    can_update = Column(Boolean, nullable=False, default=False)
    can_delete = Column(Boolean, nullable=False, default=False)
    granted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    document = relationship("Document")
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])
