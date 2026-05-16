from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db.base import Base


class WarehouseItem(Base):
    __tablename__ = "warehouse_items"
    __table_args__ = (
        UniqueConstraint("company_id", "model_id", "color"),
        Index("ix_warehouse_items_company_id", "company_id"),
        Index("ix_warehouse_items_owner_id", "owner_id"),
        Index("ix_warehouse_items_model_id", "model_id"),
        Index("ix_warehouse_items_color", "color"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="CASCADE"), nullable=False)
    color = Column(String, nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    unit_cost = Column(Numeric(14, 2), nullable=True)
    unit_current_value = Column(Numeric(14, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="warehouse_items")
    model = relationship("ManagedModel")


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
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    purchase_cost = Column(Numeric(14, 2), nullable=True)
    current_estimated_value = Column(Numeric(14, 2), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="owned_properties")


def decimal_or_zero(value: Decimal | None) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")
