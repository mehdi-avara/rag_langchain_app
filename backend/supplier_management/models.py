from __future__ import annotations

import enum
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    Date,
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


class SupplierType(str, enum.Enum):
    LOCAL = "local"
    INTERNATIONAL = "international"
    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"


class SupplierStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    BLACKLISTED = "blacklisted"


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_suppliers_company_code"),
        Index("ix_suppliers_company_id", "company_id"),
        Index("ix_suppliers_code", "code"),
        Index("ix_suppliers_name", "name"),
        Index("ix_suppliers_status", "status"),
        Index("ix_suppliers_supplier_type", "supplier_type"),
        Index("ix_suppliers_country", "country"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    supplier_type = Column(String(30), nullable=False, default=SupplierType.LOCAL.value)
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    tax_id = Column(String(100), nullable=True)
    website = Column(String(512), nullable=True)
    status = Column(String(30), nullable=False, default=SupplierStatus.PENDING.value)
    notes = Column(Text, nullable=True)
    description_embedding = Column(Vector(1024), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    contacts = relationship(
        "SupplierContact",
        back_populates="supplier",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplierContact.id",
    )
    categories = relationship(
        "SupplierCategory",
        back_populates="supplier",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplierCategory.category",
    )
    documents = relationship(
        "SupplierDocument",
        back_populates="supplier",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplierDocument.created_at.desc()",
    )
    evaluations = relationship(
        "SupplierEvaluation",
        back_populates="supplier",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplierEvaluation.evaluation_date.desc()",
    )


class SupplierContact(Base):
    __tablename__ = "supplier_contacts"
    __table_args__ = (
        Index("ix_supplier_contacts_supplier_id", "supplier_id"),
        Index("ix_supplier_contacts_email", "email"),
        Index("ix_supplier_contacts_is_primary", "is_primary"),
    )

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    full_name = Column(String(255), nullable=False)
    job_title = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="contacts")


class SupplierCategory(Base):
    __tablename__ = "supplier_categories"
    __table_args__ = (
        UniqueConstraint("supplier_id", "category", name="uq_supplier_categories_supplier_category"),
        Index("ix_supplier_categories_supplier_id", "supplier_id"),
        Index("ix_supplier_categories_category", "category"),
    )

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="categories")


class SupplierDocument(Base):
    __tablename__ = "supplier_documents"
    __table_args__ = (
        Index("ix_supplier_documents_supplier_id", "supplier_id"),
        Index("ix_supplier_documents_asset_id", "asset_id"),
        Index("ix_supplier_documents_document_type", "document_type"),
        Index("ix_supplier_documents_expires_at", "expires_at"),
    )

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True)
    document_type = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    expires_at = Column(Date, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="documents")
    asset = relationship("FileAsset")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class SupplierEvaluation(Base):
    __tablename__ = "supplier_evaluations"
    __table_args__ = (
        Index("ix_supplier_evaluations_supplier_id", "supplier_id"),
        Index("ix_supplier_evaluations_evaluator_user_id", "evaluator_user_id"),
        Index("ix_supplier_evaluations_evaluation_date", "evaluation_date"),
    )

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    evaluator_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    quality_score = Column(Numeric(5, 2), nullable=True)
    delivery_score = Column(Numeric(5, 2), nullable=True)
    price_score = Column(Numeric(5, 2), nullable=True)
    service_score = Column(Numeric(5, 2), nullable=True)
    notes = Column(Text, nullable=True)
    evaluation_date = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="evaluations")
    evaluator = relationship("User", foreign_keys=[evaluator_user_id])
