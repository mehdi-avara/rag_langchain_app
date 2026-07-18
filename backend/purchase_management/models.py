"""SQLAlchemy models for purchase_management.

Tables:
  purchase_orders              — purchase-order header
  purchase_order_lines         — normalized commercial order lines
  purchase_phases              — physical delivery batches
  purchase_phase_allocations   — allocation of PO lines across delivery phases
  purchase_phase_items         — legacy compatibility table
  purchase_order_costs         — freight, customs, tax, insurance, and other costs
  purchase_order_receipt_links — financial receipt links
"""
from __future__ import annotations

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
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
    PARTIALLY_RECEIVED = "partially_received"
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
        UniqueConstraint(
            "company_id",
            "reference_number",
            name="uq_po_company_reference",
        ),
        UniqueConstraint(
            "company_id",
            "rfq_id",
            name="uq_purchase_orders_company_rfq",
        ),
        CheckConstraint(
            """
            NOT (
                rfq_id IS NOT NULL
                AND source_material_requisition_id IS NOT NULL
            )
            """,
            name="single_source",
        ),
        Index("ix_purchase_orders_company_id", "company_id"),
        Index("ix_purchase_orders_status", "status"),
        Index(
            "ix_purchase_orders_approval_status",
            "approval_status",
        ),
        Index(
            "ix_purchase_orders_created_by_user_id",
            "created_by_user_id",
        ),
        Index(
            "ix_purchase_orders_source_material_requisition_id",
            "source_material_requisition_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference_number = Column(String(50), nullable=False, index=True)
    title = Column(String(255), nullable=True)

    rfq_id = Column(
        Integer,
        ForeignKey("rfqs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_material_requisition_id = Column(
        Integer,
        ForeignKey(
            "material_requisitions.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    winning_quotation_response_id = Column(
        Integer,
        ForeignKey(
            "quotation_responses.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    supplier_name = Column(String(255), nullable=True, index=True)

    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=False,
        default=1,
    )

    status = Column(
        String(20),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT.value,
    )
    approval_status = Column(
        String(20),
        nullable=False,
        default=PurchaseApprovalStatus.DRAFT.value,
    )

    description = Column(Text, nullable=True)
    description_embedding = Column(Vector(1024), nullable=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    base_currency = relationship(
        "Currency",
        foreign_keys=[base_currency_id],
    )
    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    approved_by = relationship(
        "User",
        foreign_keys=[approved_by_user_id],
    )

    lines = relationship(
        "PurchaseOrderLine",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PurchaseOrderLine.line_number",
    )
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


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id",
            "line_number",
            name="uq_purchase_order_lines_order_line_number",
        ),
        CheckConstraint(
            "line_number >= 1",
            name="line_number_positive",
        ),
        CheckConstraint(
            "ordered_quantity > 0",
            name="quantity_positive",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="unit_price_nonnegative",
        ),
        CheckConstraint(
            "unit_price_base >= 0",
            name="unit_price_base_nonnegative",
        ),
        CheckConstraint(
            "exchange_rate_used > 0",
            name="exchange_rate_positive",
        ),
        Index(
            "ix_purchase_order_lines_purchase_order_id",
            "purchase_order_id",
        ),
        Index(
            "ix_purchase_order_lines_item_id",
            "item_id",
        ),
        Index(
            "ix_purchase_order_lines_unit_id",
            "unit_id",
        ),
        Index(
            "ix_purchase_order_lines_currency_id",
            "currency_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number = Column(Integer, nullable=False)
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordered_quantity = Column(
        Numeric(18, 4),
        nullable=False,
    )
    unit_id = Column(
        Integer,
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_description = Column(Text, nullable=True)
    unit_price = Column(
        Numeric(28, 10),
        nullable=False,
    )
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_price_base = Column(
        Numeric(28, 10),
        nullable=False,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=False,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="lines",
    )
    currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    allocations = relationship(
        "PurchasePhaseAllocation",
        back_populates="purchase_order_line",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PurchasePhaseAllocation.id",
    )


class PurchasePhase(Base):
    __tablename__ = "purchase_phases"
    __table_args__ = (
        Index(
            "ix_purchase_phases_purchase_order_id",
            "purchase_order_id",
        ),
        Index("ix_purchase_phases_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_number = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default=PurchasePhaseStatus.DRAFT.value,
    )

    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=True,
    )

    expected_delivery_date = Column(DateTime, nullable=True)
    actual_delivery_date = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="phases",
    )
    currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    allocations = relationship(
        "PurchasePhaseAllocation",
        back_populates="phase",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PurchasePhaseAllocation.id",
    )
    items = relationship(
        "PurchasePhaseItem",
        back_populates="phase",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PurchasePhaseAllocation(Base):
    __tablename__ = "purchase_phase_allocations"
    __table_args__ = (
        UniqueConstraint(
            "phase_id",
            "purchase_order_line_id",
            name="uq_purchase_phase_allocations_phase_line",
        ),
        CheckConstraint(
            "allocated_quantity > 0",
            name="quantity_positive",
        ),
        Index(
            "ix_purchase_phase_allocations_phase_id",
            "phase_id",
        ),
        Index(
            "ix_purchase_phase_allocations_order_line_id",
            "purchase_order_line_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    phase_id = Column(
        Integer,
        ForeignKey("purchase_phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_order_line_id = Column(
        Integer,
        ForeignKey(
            "purchase_order_lines.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    allocated_quantity = Column(
        Numeric(18, 4),
        nullable=False,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    phase = relationship(
        "PurchasePhase",
        back_populates="allocations",
    )
    purchase_order_line = relationship(
        "PurchaseOrderLine",
        back_populates="allocations",
    )


class PurchasePhaseItem(Base):
    __tablename__ = "purchase_phase_items"
    __table_args__ = (
        Index(
            "ix_purchase_phase_items_phase_id",
            "phase_id",
        ),
        Index(
            "ix_purchase_phase_items_item_id",
            "item_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    phase_id = Column(
        Integer,
        ForeignKey("purchase_phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )

    item_name = Column(String(255), nullable=False)
    item_code = Column(String(100), nullable=True, index=True)

    quantity = Column(Numeric(18, 4), nullable=False)
    received_quantity = Column(
        Numeric(18, 4),
        nullable=False,
        default=0,
    )
    unit = Column(String(30), nullable=False, default="pcs")

    unit_price = Column(
        Numeric(28, 10),
        nullable=False,
        default=0,
    )
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_price_base = Column(
        Numeric(28, 10),
        nullable=False,
        default=0,
    )
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=False,
        default=1,
    )

    line_total = Column(
        Numeric(28, 10),
        nullable=False,
        default=0,
    )
    line_total_base = Column(
        Numeric(28, 10),
        nullable=False,
        default=0,
    )

    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    phase = relationship(
        "PurchasePhase",
        back_populates="items",
    )
    currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    base_currency = relationship(
        "Currency",
        foreign_keys=[base_currency_id],
    )


class PurchaseOrderCost(Base):
    __tablename__ = "purchase_order_costs"
    __table_args__ = (
        Index(
            "ix_purchase_order_costs_purchase_order_id",
            "purchase_order_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    cost_type = Column(String(30), nullable=False)
    description = Column(Text, nullable=True)

    amount = Column(Numeric(28, 10), nullable=False)
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_base = Column(Numeric(28, 10), nullable=False)
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=False,
        default=1,
    )

    allocation_method = Column(
        String(20),
        nullable=False,
        default=CostAllocationMethod.PER_VALUE.value,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="costs",
    )
    currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    base_currency = relationship(
        "Currency",
        foreign_keys=[base_currency_id],
    )


class PurchaseOrderReceiptLink(Base):
    __tablename__ = "purchase_order_receipt_links"
    __table_args__ = (
        Index(
            "ix_po_receipt_links_purchase_order_id",
            "purchase_order_id",
        ),
        Index(
            "ix_po_receipt_links_financial_receipt_id",
            "financial_receipt_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    financial_receipt_id = Column(Integer, nullable=False)
    linked_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    linked_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="receipt_links",
    )
    linked_by = relationship(
        "User",
        foreign_keys=[linked_by_user_id],
    )
