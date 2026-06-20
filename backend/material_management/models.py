from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base


class ItemType(str, enum.Enum):
    MATERIAL = "material"
    SPARE_PART = "spare_part"
    CONSUMABLE = "consumable"
    TOOL = "tool"
    CHEMICAL = "chemical"
    PPE = "ppe"


class UnitType(str, enum.Enum):
    MASS = "mass"
    VOLUME = "volume"
    LENGTH = "length"
    COUNT = "count"
    AREA = "area"


class ItemCategory(Base):
    __tablename__ = "item_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_item_categories_company_code"),
        Index("ix_item_categories_company_id", "company_id"),
        Index("ix_item_categories_code", "code"),
        Index("ix_item_categories_parent_id", "parent_id"),
        Index("ix_item_categories_name", "name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True)
    code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    parent = relationship("ItemCategory", remote_side=[id], back_populates="children")
    children = relationship("ItemCategory", back_populates="parent", passive_deletes=True)
    items = relationship("Item", back_populates="category")


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_units_company_code"),
        Index("ix_units_company_id", "company_id"),
        Index("ix_units_code", "code"),
        Index("ix_units_unit_type", "unit_type"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    unit_type = Column(String(30), nullable=False, default=UnitType.COUNT.value)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    items = relationship("Item", back_populates="unit")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("company_id", "item_code", name="uq_items_company_item_code"),
        Index("ix_items_company_id", "company_id"),
        Index("ix_items_item_code", "item_code"),
        Index("ix_items_name", "name"),
        Index("ix_items_category_id", "category_id"),
        Index("ix_items_unit_id", "unit_id"),
        Index("ix_items_model_id", "model_id"),
        Index("ix_items_item_type", "item_type"),
        Index("ix_items_is_active", "is_active"),
        Index("ix_items_is_critical", "is_critical"),
        Index("ix_items_barcode", "barcode"),
        Index("ix_items_qr_code", "qr_code"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    item_code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("item_categories.id", ondelete="RESTRICT"), nullable=False)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False)
    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="SET NULL"), nullable=True)
    specs = Column(JSONB, nullable=False, default=dict)
    barcode = Column(String(255), nullable=True)
    qr_code = Column(String(255), nullable=True)
    item_type = Column(String(30), nullable=False, default=ItemType.MATERIAL.value)
    is_active = Column(Boolean, nullable=False, default=True)
    is_critical = Column(Boolean, nullable=False, default=False)
    lead_time_days = Column(Integer, nullable=True)
    description_embedding = Column(Vector(1024), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    category = relationship("ItemCategory", back_populates="items")
    unit = relationship("Unit", back_populates="items")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    alternatives = relationship(
        "ItemAlternative",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ItemAlternative.id",
    )
    documents = relationship(
        "ItemDocument",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ItemDocument.created_at.desc()",
    )


class ItemAlternative(Base):
    __tablename__ = "item_alternatives"
    __table_args__ = (
        UniqueConstraint("item_id", "alt_code", name="uq_item_alternatives_item_alt_code"),
        Index("ix_item_alternatives_item_id", "item_id"),
        Index("ix_item_alternatives_supplier_id", "supplier_id"),
        Index("ix_item_alternatives_alt_code", "alt_code"),
    )

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    alt_code = Column(String(100), nullable=False)
    alt_name = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    item = relationship("Item", back_populates="alternatives")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class ItemDocument(Base):
    __tablename__ = "item_documents"
    __table_args__ = (
        Index("ix_item_documents_item_id", "item_id"),
        Index("ix_item_documents_asset_id", "asset_id"),
        Index("ix_item_documents_document_type", "document_type"),
    )

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True)
    document_type = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    item = relationship("Item", back_populates="documents")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
