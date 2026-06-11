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


class FinancialDirection(str, enum.Enum):
    INPUT = "input"
    OUTPUT = "output"


class FinancialAccessMethod(str, enum.Enum):
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    EMAIL = "email"
    PHONE = "phone"
    WECHAT = "we-chat"


class FinancialCard(Base):
    __tablename__ = "financial_cards"
    __table_args__ = (
        UniqueConstraint("company_id", "card_number"),
        Index("ix_financial_cards_company_id", "company_id"),
        Index("ix_financial_cards_owner_id", "owner_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False, index=True)
    card_number = Column(String, nullable=False, index=True)
    bank_name = Column(String, nullable=True, index=True)
    account_owner_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="financial_cards")
    receipts = relationship("FinancialReceipt", back_populates="credit_card")


class FinancialCustomer(Base):
    __tablename__ = "financial_customers"
    __table_args__ = (
        Index("ix_financial_customers_company_id", "company_id"),
        Index("ix_financial_customers_owner_id", "owner_id"),
        Index("ix_financial_customers_name", "name"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False, index=True)
    phone_number1 = Column(String, nullable=False, index=True)
    phone_number2 = Column(String, nullable=True, index=True)
    access_method = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="financial_customers")
    receipts = relationship("FinancialReceipt", back_populates="customer")


class FinancialReceipt(Base):
    __tablename__ = "financial_receipts"
    __table_args__ = (
        Index("ix_financial_receipts_company_id", "company_id"),
        Index("ix_financial_receipts_owner_id", "owner_id"),
        Index("ix_financial_receipts_credit_card_id", "credit_card_id"),
        Index("ix_financial_receipts_customer_id", "customer_id"),
        Index("ix_financial_receipts_tracking_number", "tracking_number"),
        Index("ix_financial_receipts_counterparty_name", "counterparty_name"),
        Index("ix_financial_receipts_direction", "direction"),
        Index("ix_financial_receipts_receipt_date", "receipt_date"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credit_card_id = Column(Integer, ForeignKey("financial_cards.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("financial_customers.id"), nullable=True)
    description = Column(Text, nullable=False)
    description_embedding = Column(Vector(1024), nullable=True)
    tracking_number = Column(String, nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    direction = Column(String, nullable=False, index=True)
    counterparty_name = Column(String, nullable=False, index=True)
    receipt_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company")
    owner = relationship("User", back_populates="financial_receipts")
    credit_card = relationship("FinancialCard", back_populates="receipts")
    customer = relationship("FinancialCustomer", back_populates="receipts")
    files = relationship(
        "FinancialReceiptFile",
        back_populates="receipt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    comment_links = relationship(
        "FinancialReceiptCommentLink",
        back_populates="receipt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FinancialReceiptFile(Base):
    __tablename__ = "financial_receipt_files"
    __table_args__ = (
        Index("ix_financial_receipt_files_receipt_id", "receipt_id"),
        Index("ix_financial_receipt_files_user_id", "user_id"),
        Index("ix_financial_receipt_files_asset_id", "asset_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    receipt_id = Column(Integer, ForeignKey("financial_receipts.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True)
    file_name = Column(String, nullable=False)
    media_address = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    receipt = relationship("FinancialReceipt", back_populates="files")
    user = relationship("User", back_populates="financial_receipt_files")
    asset = relationship("FileAsset")


class FinancialReceiptCommentLink(Base):
    __tablename__ = "financial_receipt_comment_links"
    __table_args__ = (
        Index("ix_financial_receipt_comment_links_receipt_id", "receipt_id"),
        Index("ix_financial_receipt_comment_links_comment_id", "comment_id"),
    )

    receipt_id = Column(Integer, ForeignKey("financial_receipts.id", ondelete="CASCADE"), primary_key=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True)
    linked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note = Column(Text, nullable=True)
    note_embedding = Column(Vector(1024), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    receipt = relationship("FinancialReceipt", back_populates="comment_links")
    comment = relationship("Comment")
    linked_by = relationship("User")
