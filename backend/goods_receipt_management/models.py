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


class GoodsReceiptStatus(str, enum.Enum):
    DRAFT = "draft"
    POSTED = "posted"


class GoodsReceiptNote(Base):
    __tablename__ = "goods_receipt_notes"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "grn_number",
            name="uq_grn_company_number",
        ),
        Index("ix_grn_company_id", "company_id"),
        Index("ix_grn_number", "grn_number"),
        Index(
            "ix_grn_purchase_order_id",
            "purchase_order_id",
        ),
        Index(
            "ix_grn_purchase_phase_id",
            "purchase_phase_id",
        ),
        Index(
            "ix_grn_received_by_user_id",
            "received_by_user_id",
        ),
        Index("ix_grn_receipt_date", "receipt_date"),
        Index("ix_grn_status", "status"),
        Index(
            "ix_grn_delivery_note_number",
            "delivery_note_number",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    grn_number = Column(String(50), nullable=False)
    purchase_order_id = Column(
        Integer,
        ForeignKey(
            "purchase_orders.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    purchase_phase_id = Column(
        Integer,
        ForeignKey(
            "purchase_phases.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    received_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    receipt_date = Column(Date, nullable=False)
    delivery_note_number = Column(
        String(100),
        nullable=True,
    )
    warehouse_id = Column(
        Integer,
        ForeignKey(
            "warehouses.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    status = Column(
        String(20),
        nullable=False,
        default=GoodsReceiptStatus.DRAFT.value,
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

    items = relationship(
        "GoodsReceiptItem",
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GoodsReceiptItem.created_at",
    )


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        UniqueConstraint(
            "goods_receipt_note_id",
            "purchase_phase_allocation_id",
            name="uq_grn_items_phase_allocation",
        ),
        Index(
            "ix_grn_items_grn_id",
            "goods_receipt_note_id",
        ),
        Index(
            "ix_grn_items_phase_allocation_id",
            "purchase_phase_allocation_id",
        ),
        Index("ix_grn_items_item_id", "item_id"),
        Index(
            "ix_grn_items_storage_location_id",
            "storage_location_id",
        ),
        Index(
            "ix_grn_items_currency_id",
            "currency_id",
        ),
        Index(
            "ix_grn_items_base_currency_id",
            "base_currency_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    goods_receipt_note_id = Column(
        Integer,
        ForeignKey(
            "goods_receipt_notes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    purchase_phase_allocation_id = Column(
        Integer,
        ForeignKey(
            "purchase_phase_allocations.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_code = Column(String(100), nullable=True)
    item_name = Column(String(255), nullable=False)
    unit_code = Column(String(30), nullable=False)
    received_quantity = Column(
        Numeric(18, 4),
        nullable=False,
    )
    accepted_quantity = Column(
        Numeric(18, 4),
        nullable=False,
    )
    rejected_quantity = Column(
        Numeric(18, 4),
        nullable=False,
    )
    rejection_reason = Column(Text, nullable=True)
    storage_location_id = Column(
        Integer,
        ForeignKey(
            "storage_locations.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    unit_cost = Column(
        Numeric(28, 10),
        nullable=False,
    )
    currency_id = Column(
        Integer,
        ForeignKey(
            "currencies.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    unit_cost_base = Column(
        Numeric(28, 10),
        nullable=False,
    )
    base_currency_id = Column(
        Integer,
        ForeignKey(
            "currencies.id",
            ondelete="RESTRICT",
        ),
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

    goods_receipt = relationship(
        "GoodsReceiptNote",
        back_populates="items",
    )
    purchase_phase_allocation = relationship(
        "PurchasePhaseAllocation",
        foreign_keys=[purchase_phase_allocation_id],
    )
