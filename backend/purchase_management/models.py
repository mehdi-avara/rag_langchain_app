"""SQLAlchemy models for purchase_management.

Tables:
  purchase_orders          — the purchase order header
  purchase_phases          — one PO has 1..N phases (physical delivery batches)
  purchase_phase_items     — line items inside each phase
  purchase_order_costs     — additional costs: freight, customs, tax, insurance
  purchase_order_receipt_links — links to financial_management receipt IDs (plain INT, no FK import)
"""
from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
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


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    ORDERED = "ordered"
    SHIPPED = "shipped"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PurchaseApprovalStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PurchasePhaseStatus(str, enum.Enum):
    DRAFT = "draft"
    ORDERED = "ordered"
    SHIPPED = "shipped"
    RECEIVED = "received"
    CLOSED = "closed"


class PurchaseCostType(str, enum.Enum):
    FREIGHT = "freight"
    CUSTOMS = "customs"
    TAX = "tax"
    INSURANCE = "insurance"
    OTHER = "other"


class CostAllocationMethod(str, enum.Enum):
    PER_ITEM = "per_item"
    PER_VALUE = "per_value"
    MANUAL = "manual"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("company_id", "reference_number", name="uq_po_company_reference"),
        Index("ix_purchase_orders_company_id", "company_id"),
        Index("ix_purchase_orders_status", "status"),
        Index("ix_purchase_orders_approval_status", "approval_status"),
        Index("ix_purchase_orders_created_by_user_id", "created_by_user_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    reference_number = Column(String(50), nullable=False, index=True)
    title = Column(String(255), nullable=True)

    # Phase 0: free-text supplier; Phase 1: FK to suppliers.id
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_name = Column(String(255), nullable=True, index=True)

    # Multi-currency (Phase 0.3 must run first)
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    base_currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    exchange_rate_used = Column(Numeric(28, 10), nullable=False, default=1)

    # Indexes for status/approval_status are declared in __table_args__;
    # no column-level index= here (would create a duplicate index name).
    status = Column(String(20), nullable=False, default=PurchaseOrderStatus.DRAFT.value)
    approval_status = Column(String(20), nullable=False, default=PurchaseApprovalStatus.DRAFT.value)

    description = Column(Text, nullable=True)
    # Semantic search embedding (nullable — generated on demand)
    description_embedding = Column(Vector(1024), nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (only to models owned by THIS module or shared)
    company = relationship("Company")
    currency = relationship("Currency", foreign_keys=[currency_id])
    base_currency = relationship("Currency", foreign_keys=[base_currency_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])

    phases = relationship(
        "PurchasePhase",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PurchasePhase.phase_number",
    )
    costs = relationship(
        "PurchaseOrderCost",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    receipt_links = relationship(
        "PurchaseOrderReceiptLink",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PurchasePhase(Base):
    __tablename__ = "purchase_phases"
    __table_args__ = (
        Index("ix_purchase_phases_purchase_order_id", "purchase_order_id"),
        Index("ix_purchase_phases_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    phase_number = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    # Index for status is declared in __table_args__ (no duplicate here).
    status = Column(String(20), nullable=False, default=PurchasePhaseStatus.DRAFT.value)

    # Phase-level currency — inherits from PO if null
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=True)
    exchange_rate_used = Column(Numeric(28, 10), nullable=True)

    expected_delivery_date = Column(DateTime, nullable=True)
    actual_delivery_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="phases")
    currency = relationship("Currency", foreign_keys=[currency_id])
    items = relationship(
        "PurchasePhaseItem",
        back_populates="phase",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PurchasePhaseItem(Base):
    __tablename__ = "purchase_phase_items"
    __table_args__ = (
        Index("ix_purchase_phase_items_phase_id", "phase_id"),
    )

    id = Column(Integer, primary_key=True)
    phase_id = Column(Integer, ForeignKey("purchase_phases.id", ondelete="CASCADE"), nullable=False)

    # Phase 0: free text; Phase 1: FK to material_management items
    item_name = Column(String(255), nullable=False)
    item_code = Column(String(100), nullable=True, index=True)

    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(30), nullable=False, default="pcs")

    # Multi-currency money fields (4-field pattern)
    unit_price = Column(Numeric(28, 10), nullable=False, default=0)
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    unit_price_base = Column(Numeric(28, 10), nullable=False, default=0)
    base_currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    exchange_rate_used = Column(Numeric(28, 10), nullable=False, default=1)

    line_total = Column(Numeric(28, 10), nullable=False, default=0)
    line_total_base = Column(Numeric(28, 10), nullable=False, default=0)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    phase = relationship("PurchasePhase", back_populates="items")
    currency = relationship("Currency", foreign_keys=[currency_id])
    base_currency = relationship("Currency", foreign_keys=[base_currency_id])


class PurchaseOrderCost(Base):
    __tablename__ = "purchase_order_costs"
    __table_args__ = (
        Index("ix_purchase_order_costs_purchase_order_id", "purchase_order_id"),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    cost_type = Column(String(30), nullable=False)  # freight | customs | tax | insurance | other
    description = Column(Text, nullable=True)

    # Multi-currency money fields
    amount = Column(Numeric(28, 10), nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    amount_base = Column(Numeric(28, 10), nullable=False)
    base_currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="RESTRICT"), nullable=False)
    exchange_rate_used = Column(Numeric(28, 10), nullable=False, default=1)

    allocation_method = Column(String(20), nullable=False, default=CostAllocationMethod.PER_VALUE.value)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="costs")
    currency = relationship("Currency", foreign_keys=[currency_id])
    base_currency = relationship("Currency", foreign_keys=[base_currency_id])


class PurchaseOrderReceiptLink(Base):
    """Links a financial receipt (from financial_management) to a purchase order.

    IMPORTANT: financial_receipt_id is stored as a plain Integer — NOT as an ORM FK.
    This maintains module isolation (no import from financial_management.models).
    Integrity is enforced at the application layer when creating the link.
    """
    __tablename__ = "purchase_order_receipt_links"
    __table_args__ = (
        Index("ix_po_receipt_links_purchase_order_id", "purchase_order_id"),
        Index("ix_po_receipt_links_financial_receipt_id", "financial_receipt_id"),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    financial_receipt_id = Column(Integer, nullable=False)  # plain ID, no FK import
    linked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="receipt_links")
    linked_by = relationship("User", foreign_keys=[linked_by_user_id])
