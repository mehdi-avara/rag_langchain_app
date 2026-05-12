from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from db.base import Base


class SystemTag(Base):
    __tablename__ = "system_tags"
    __table_args__ = (
        UniqueConstraint("company_id", "tag_name"),
        Index("ix_system_tags_company_id", "company_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    father_tag_id = Column(Integer, ForeignKey("system_tags.id"), nullable=True)
    tag_name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="system_tags")

    parent = relationship(
        "SystemTag",
        remote_side=[id],
        back_populates="children",
    )

    children = relationship(
        "SystemTag",
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,
    )
