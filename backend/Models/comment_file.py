from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from db.base import Base


class CommentFile(Base):
    __tablename__ = "comment_files"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer,ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String, nullable=False)
    media_address = Column(String, nullable=False)

    comment = relationship("Comment", back_populates="files")
    user = relationship("User", back_populates="files")
