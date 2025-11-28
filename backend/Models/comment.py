from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from pgvector.sqlalchemy import Vector

from db.base import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)