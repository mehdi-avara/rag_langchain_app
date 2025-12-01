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
    system_tag_id = Column(Integer,ForeignKey("system_tags.id", ondelete="CASCADE"),nullable=False)
    filename = Column(String, nullable=False)
    n_pages = Column(Integer, nullable=False)
    n_chunks = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    
    abstract = Column(Text)
    file_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship("User", back_populates="documents")
    system_tag = relationship("SystemTag", back_populates="documents")    
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="document", passive_deletes=True,)