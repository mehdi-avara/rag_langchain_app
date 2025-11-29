from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from db.base import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    system_tag_id = Column(
        Integer,
        ForeignKey("system_tags.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    doc_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    chunk_id = Column(
        Integer,
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    content = Column(Text, nullable=False)
    media_address = Column(String, nullable=True)
    embedding = Column(Vector(1024), nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow, 
    )

    # ------------ RELATIONSHIPS ------------
    user = relationship("User", back_populates="comments")
    system_tag = relationship("SystemTag", back_populates="comments")
    document = relationship("Document", back_populates="comments")
    chunk = relationship("Chunk", back_populates="comments")
    
    