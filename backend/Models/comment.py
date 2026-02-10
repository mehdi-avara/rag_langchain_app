from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import enum

from db.base import Base


class CommentType(str, enum.Enum):
    COMMENT = "comment"
    FAILURE = "failure"
    REPAIRE = "repaire"
    REPORT = "report"
    


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True)
    type = Column(String, nullable=False, default="comment")
    
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow, 
    )

    # ------------ RELATIONSHIPS ------------
    user = relationship("User", back_populates="comments")
    files = relationship(
        "CommentFile",
        back_populates="comment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    
    
