from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from db.base import Base


class OwnedProperty(Base):
    __tablename__ = "owned_properties"
    __table_args__ = (
        Index("ix_owned_properties_company_id", "company_id"),
        Index("ix_owned_properties_owner_id", "owner_id"),
        Index("ix_owned_properties_category", "category"),
        Index("ix_owned_properties_title", "title"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    purchase_cost = Column(Numeric(24, 2), nullable=True)
    current_estimated_value = Column(Numeric(24, 2), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    owner = relationship("User", back_populates="owned_properties")
