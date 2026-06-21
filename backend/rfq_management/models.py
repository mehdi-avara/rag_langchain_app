from __future__ import annotations

import enum
from datetime import datetime

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


class RFQStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class RFQSupplierResponseStatus(str, enum.Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    DECLINED = "declined"


class RequestForQuotation(Base):
    __tablename__ = "rfqs"
    __table_args__ = (
        UniqueConstraint("company_id", "rfq_number", name="uq_rfqs_company_number"),
        UniqueConstraint("company_id", "mr_id", name="uq_rfqs_company_mr"),
        Index("ix_rfqs_company_id", "company_id"),
        Index("ix_rfqs_rfq_number", "rfq_number"),
        Index("ix_rfqs_mr_id", "mr_id"),
        Index("ix_rfqs_status", "status"),
        Index("ix_rfqs_deadline_date", "deadline_date"),
        Index("ix_rfqs_created_by_user_id", "created_by_user_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    rfq_number = Column(String(50), nullable=False)
    mr_id = Column(
        Integer,
        ForeignKey("material_requisitions.id", ondelete="SET NULL"),
        nullable=True,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    deadline_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default=RFQStatus.DRAFT.value)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    company = relationship("Company")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    suppliers = relationship(
        "RFQSupplier",
        back_populates="rfq",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RFQSupplier.created_at",
    )
    items = relationship(
        "RFQItem",
        back_populates="rfq",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RFQItem.created_at",
    )
    responses = relationship(
        "QuotationResponse",
        back_populates="rfq",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuotationResponse.received_at",
    )


class RFQSupplier(Base):
    __tablename__ = "rfq_suppliers"
    __table_args__ = (
        UniqueConstraint(
            "rfq_id",
            "supplier_id",
            name="uq_rfq_suppliers_rfq_supplier",
        ),
        Index("ix_rfq_suppliers_rfq_id", "rfq_id"),
        Index("ix_rfq_suppliers_supplier_id", "supplier_id"),
        Index("ix_rfq_suppliers_response_status", "response_status"),
    )

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_code = Column(String(50), nullable=True)
    supplier_name = Column(String(255), nullable=False)
    sent_at = Column(DateTime, nullable=True)
    response_status = Column(
        String(20),
        nullable=False,
        default=RFQSupplierResponseStatus.PENDING.value,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rfq = relationship("RequestForQuotation", back_populates="suppliers")


class RFQItem(Base):
    __tablename__ = "rfq_items"
    __table_args__ = (
        Index("ix_rfq_items_rfq_id", "rfq_id"),
        Index("ix_rfq_items_item_id", "item_id"),
        Index("ix_rfq_items_unit_id", "unit_id"),
        Index("ix_rfq_items_item_code", "item_code"),
        Index("ix_rfq_items_item_name", "item_name"),
    )

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
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
    specifications = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rfq = relationship("RequestForQuotation", back_populates="items")


class QuotationResponse(Base):
    __tablename__ = "quotation_responses"
    __table_args__ = (
        UniqueConstraint(
            "rfq_id",
            "supplier_id",
            name="uq_quote_responses_rfq_supplier",
        ),
        Index("ix_quote_responses_rfq_id", "rfq_id"),
        Index("ix_quote_responses_supplier_id", "supplier_id"),
        Index("ix_quote_responses_is_winner", "is_winner"),
        Index("ix_quote_responses_received_at", "received_at"),
        Index("ix_quote_responses_valid_until", "valid_until"),
    )

    id = Column(Integer, primary_key=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_code = Column(String(50), nullable=True)
    supplier_name = Column(String(255), nullable=False)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    valid_until = Column(Date, nullable=True)
    payment_terms = Column(Text, nullable=True)
    delivery_days = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    is_winner = Column(Boolean, nullable=False, default=False)
    selected_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rfq = relationship("RequestForQuotation", back_populates="responses")
    selected_by = relationship("User", foreign_keys=[selected_by_user_id])
    items = relationship(
        "QuotationResponseItem",
        back_populates="response",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuotationResponseItem.created_at",
    )


class QuotationResponseItem(Base):
    __tablename__ = "quotation_response_items"
    __table_args__ = (
        UniqueConstraint(
            "quotation_response_id",
            "rfq_item_id",
            name="uq_quote_items_response_rfq_item",
        ),
        Index("ix_quote_items_response_id", "quotation_response_id"),
        Index("ix_quote_items_rfq_item_id", "rfq_item_id"),
        Index("ix_quote_items_currency_id", "currency_id"),
        Index("ix_quote_items_base_currency_id", "base_currency_id"),
    )

    id = Column(Integer, primary_key=True)
    quotation_response_id = Column(
        Integer,
        ForeignKey("quotation_responses.id", ondelete="CASCADE"),
        nullable=False,
    )
    rfq_item_id = Column(
        Integer,
        ForeignKey("rfq_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    unit_price = Column(Numeric(28, 10), nullable=False)
    currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    unit_price_base = Column(Numeric(28, 10), nullable=False)
    base_currency_id = Column(
        Integer,
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate_used = Column(Numeric(28, 10), nullable=False)
    lead_time_days = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    response = relationship("QuotationResponse", back_populates="items")
