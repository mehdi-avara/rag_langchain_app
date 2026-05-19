from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from db.base import Base


class BuyingProcessStatus(str, enum.Enum):
    DRAFT = "draft"
    ORDERED = "ordered"
    PAID = "paid"
    SHIPPED = "shipped"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class BuyingReceiptPurpose(str, enum.Enum):
    PRODUCT_PAYMENT = "product_payment"
    TRANSPORTATION = "transportation"
    CUSTOMS = "customs"
    TAX = "tax"
    COMMISSION = "commission"
    REFUND = "refund"
    OTHER = "other"


class BuyingCostType(str, enum.Enum):
    TRANSPORTATION = "transportation"
    CUSTOMS = "customs"
    TAX = "tax"
    COMMISSION = "commission"
    PACKAGING = "packaging"
    STORAGE = "storage"
    OTHER = "other"


class BuyingCostAllocationMethod(str, enum.Enum):
    BY_QUANTITY = "by_quantity"
    BY_VALUE = "by_value"
    MANUAL = "manual"


class BuyingProcess(Base):
    __tablename__ = "buying_processes"
    __table_args__ = (
        Index("ix_buying_processes_company_id", "company_id"),
        Index("ix_buying_processes_owner_id", "owner_id"),
        Index("ix_buying_processes_status", "status"),
        Index("ix_buying_processes_purchase_date", "purchase_date"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False, index=True)
    supplier_name = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default=BuyingProcessStatus.DRAFT.value, index=True)
    currency = Column(String, nullable=False)
    base_currency = Column(String, nullable=False)
    exchange_rate_to_base = Column(Numeric(18, 6), nullable=False)
    purchase_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    description = Column(Text, nullable=True)
    affects_warehouse = Column(Boolean, nullable=False, default=False)
    warehouse_applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User")
    items = relationship(
        "BuyingProcessItem",
        back_populates="buying_process",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    receipt_links = relationship(
        "BuyingProcessReceiptLink",
        back_populates="buying_process",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    costs = relationship(
        "BuyingProcessCost",
        back_populates="buying_process",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BuyingProcessItem(Base):
    __tablename__ = "buying_process_items"
    __table_args__ = (
        Index("ix_buying_process_items_buying_process_id", "buying_process_id"),
        Index("ix_buying_process_items_model_id", "model_id"),
    )

    id = Column(Integer, primary_key=True)
    buying_process_id = Column(Integer, ForeignKey("buying_processes.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey("managed_models.id", ondelete="CASCADE"), nullable=False)
    color = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False)
    exchange_rate_to_base = Column(Numeric(18, 6), nullable=False)
    unit_price_base = Column(Numeric(14, 2), nullable=False)
    line_total = Column(Numeric(14, 2), nullable=False)
    line_total_base = Column(Numeric(14, 2), nullable=False)
    allocated_cost_base = Column(Numeric(14, 2), nullable=False, default=0)
    final_unit_cost_base = Column(Numeric(14, 2), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    buying_process = relationship("BuyingProcess", back_populates="items")
    model = relationship("ManagedModel")


class BuyingProcessReceiptLink(Base):
    __tablename__ = "buying_process_receipt_links"
    __table_args__ = (
        Index("ix_buying_process_receipt_links_buying_process_id", "buying_process_id"),
        Index("ix_buying_process_receipt_links_receipt_id", "receipt_id"),
    )

    buying_process_id = Column(Integer, ForeignKey("buying_processes.id", ondelete="CASCADE"), primary_key=True)
    receipt_id = Column(Integer, ForeignKey("financial_receipts.id", ondelete="CASCADE"), primary_key=True)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    buying_process = relationship("BuyingProcess", back_populates="receipt_links")
    receipt = relationship("FinancialReceipt")
    linked_by = relationship("User")


class BuyingProcessCost(Base):
    __tablename__ = "buying_process_costs"
    __table_args__ = (
        Index("ix_buying_process_costs_buying_process_id", "buying_process_id"),
        Index("ix_buying_process_costs_receipt_id", "receipt_id"),
        Index("ix_buying_process_costs_cost_type", "cost_type"),
    )

    id = Column(Integer, primary_key=True)
    buying_process_id = Column(Integer, ForeignKey("buying_processes.id", ondelete="CASCADE"), nullable=False)
    receipt_id = Column(Integer, ForeignKey("financial_receipts.id", ondelete="SET NULL"), nullable=True)
    cost_type = Column(String, nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False)
    exchange_rate_to_base = Column(Numeric(18, 6), nullable=False)
    amount_base = Column(Numeric(14, 2), nullable=False)
    allocation_method = Column(String, nullable=False)
    manual_allocations_json = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    buying_process = relationship("BuyingProcess", back_populates="costs")
    receipt = relationship("FinancialReceipt")

