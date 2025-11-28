from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from db.base import Base


class SystemTag(Base):
    __tablename__ = "system_tags"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    father_tag_id = Column(Integer, ForeignKey("system_tags.id"), nullable=True)
    tag_name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship("User", back_populates="system_tags")
    documents = relationship("Document", back_populates="system_tag")
    
    parent = relationship(
        "SystemTag",
        remote_side=[id],
        back_populates="children",
    )

    children = relationship(
        "SystemTag",
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,  # required when using delete-orphan on self-referential rel
    )