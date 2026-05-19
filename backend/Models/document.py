from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
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
    filename = Column(String, nullable=False)
    n_pages = Column(Integer, nullable=False)
    n_chunks = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    
    abstract = Column(Text)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship("User", back_populates="documents")
    original_asset = relationship("FileAsset")
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
