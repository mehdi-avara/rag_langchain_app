from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from db.base import Base


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_num = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    vdb_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    es_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    start_pos = Column(Integer, nullable=True)
    end_pos = Column(Integer, nullable=True)
    chunk_type = Column(String, nullable=False, default="text")
    embedding = Column(Vector(1024), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    image_data = relationship("ImageChunk", back_populates="chunk", cascade="all, delete-orphan")
    document = relationship("Document", back_populates="chunks")
