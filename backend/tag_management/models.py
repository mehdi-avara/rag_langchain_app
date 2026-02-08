from datetime import datetime

from sqlalchemy import Column, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from db.base import Base


class TagModelLink(Base):
    __tablename__ = "tag_model_links"
    __table_args__ = (
        Index("ix_tag_model_links_tag_id", "tag_id"),
        Index("ix_tag_model_links_model_id", "model_id"),
    )

    tag_id = Column(Integer, ForeignKey("system_tags.id", ondelete="CASCADE"), primary_key=True)
    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="CASCADE"), primary_key=True)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    tag = relationship("SystemTag")
    model = relationship("ManagedModel")
    linked_by = relationship("User")
