from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
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


class MaterialRequisitionPriority(str, enum.Enum):
    NORMAL = "normal"
    URGENT = "urgent"
    CRITICAL = "critical"


class MaterialRequisitionStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERED = "ordered"
    CLOSED = "closed"


class MaterialRequisition(Base):
    __tablename__ = "material_requisitions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "mr_number",
            name="uq_material_requisitions_company_mr_number",
        ),
        Index("ix_material_requisitions_company_id", "company_id"),
        Index("ix_material_requisitions_mr_number", "mr_number"),
        Index("ix_material_requisitions_requested_by_user_id", "requested_by_user_id"),
        Index("ix_material_requisitions_department_id", "department_id"),
        Index(
            "ix_material_requisitions_legacy_department_id",
            "legacy_department_id",
        ),
        Index("ix_material_requisitions_status", "status"),
        Index("ix_material_requisitions_priority", "priority"),
        Index("ix_material_requisitions_needed_by_date", "needed_by_date"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    mr_number = Column(String(50), nullable=False)
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    department_id = Column(
        Integer,
        ForeignKey(
            "organization_departments.id",
            name="fk_material_requisitions_department_org",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    legacy_department_id = Column(Integer, nullable=True)
    needed_by_date = Column(Date, nullable=True)
    reason = Column(Text, nullable=False)
    priority = Column(
        String(20),
        nullable=False,
        default=MaterialRequisitionPriority.NORMAL.value,
    )
    status = Column(
        String(20),
        nullable=False,
        default=MaterialRequisitionStatus.DRAFT.value,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    department = relationship(
        "OrganizationDepartment",
        foreign_keys=[department_id],
    )
    items = relationship(
        "MaterialRequisitionItem",
        back_populates="requisition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MaterialRequisitionItem.created_at",
    )
    status_history = relationship(
        "MaterialRequisitionStatusHistory",
        back_populates="requisition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MaterialRequisitionStatusHistory.changed_at",
    )


class MaterialRequisitionItem(Base):
    __tablename__ = "material_requisition_items"
    __table_args__ = (
        Index(
            "ix_material_requisition_items_material_requisition_id",
            "material_requisition_id",
        ),
        Index("ix_material_requisition_items_item_id", "item_id"),
        Index("ix_material_requisition_items_unit_id", "unit_id"),
        Index("ix_material_requisition_items_currency_id", "currency_id"),
        Index(
            "ix_material_requisition_items_base_currency_id",
            "base_currency_id",
        ),
        Index("ix_material_requisition_items_item_code", "item_code"),
        Index("ix_material_requisition_items_item_name", "item_name"),
    )

    id = Column(Integer, primary_key=True)
    material_requisition_id = Column(
        Integer,
        ForeignKey("material_requisitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_code = Column(String(100), nullable=True)
    item_name = Column(String(255), nullable=False)
    unit_id = Column(
        Integer,
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_code = Column(String(30), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    estimated_unit_cost = Column(Numeric(28, 10), nullable=True)
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    estimated_unit_cost_base = Column(Numeric(28, 10), nullable=True)
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    exchange_rate_used = Column(Numeric(28, 10), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    requisition = relationship("MaterialRequisition", back_populates="items")


class MaterialRequisitionStatusHistory(Base):
    __tablename__ = "material_requisition_status_history"
    __table_args__ = (
        Index(
            "ix_material_requisition_status_history_material_requisition_id",
            "material_requisition_id",
        ),
        Index(
            "ix_material_requisition_status_history_changed_by_user_id",
            "changed_by_user_id",
        ),
        Index(
            "ix_material_requisition_status_history_to_status",
            "to_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    material_requisition_id = Column(
        Integer,
        ForeignKey("material_requisitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    action = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    changed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    requisition = relationship(
        "MaterialRequisition",
        back_populates="status_history",
    )
    changed_by = relationship("User", foreign_keys=[changed_by_user_id])
