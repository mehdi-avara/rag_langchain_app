from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
import enum

from db.base import Base


class DocumentStatusType(str, enum.Enum):
    INPROGGRESS = "in-proggress"
    DONE = "done"
    QUEUED = "queued"
    FAIELED = "failed"
    
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    current_version_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    n_pages = Column(Integer, nullable=False)
    n_chunks = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    
    abstract = Column(Text)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship("User", back_populates="documents")
    original_asset = relationship("FileAsset", foreign_keys=[original_asset_id])
    current_version = relationship("DocumentVersion", foreign_keys=[current_version_id], post_update=True)
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="DocumentVersion.document_id",
    )
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_document_id_version_number"),
    )

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    status = Column(String, nullable=False)
    n_pages = Column(Integer, nullable=False, default=0)
    n_chunks = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    is_current = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document", back_populates="versions", foreign_keys=[document_id])
    asset = relationship("FileAsset", foreign_keys=[asset_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    chunks = relationship("Chunk", back_populates="document_version", foreign_keys="Chunk.document_version_id")
