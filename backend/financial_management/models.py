from __future__ import annotations

import enum
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class FinancialCurrency(str, enum.Enum):
    TOMAN = "IRT"
    RIAL = "IRR"
    DOLLAR = "USD"
    DIRHAM = "AED"
    DINAR = "IQD"
    YUAN = "CNY"
    EURO = "EUR"
    POUND = "GBP"
    LIRA = "TRY"


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
        CheckConstraint(
            """
            (
                currency_id IS NULL
                AND base_currency_id IS NULL
                AND amount_base IS NULL
                AND exchange_rate_used IS NULL
            )
            OR
            (
                currency_id IS NOT NULL
                AND base_currency_id IS NOT NULL
                AND amount_base IS NOT NULL
                AND exchange_rate_used IS NOT NULL
            )
            """,
            name="canonical_money_bundle",
        ),
        CheckConstraint(
            """
            amount_base IS NULL
            OR amount_base >= 0
            """,
            name="canonical_amount_base_nonnegative",
        ),
        CheckConstraint(
            """
            exchange_rate_used IS NULL
            OR exchange_rate_used > 0
            """,
            name="canonical_rate_positive",
        ),
        Index(
            "ix_financial_receipts_company_id",
            "company_id",
        ),
        Index(
            "ix_financial_receipts_owner_id",
            "owner_id",
        ),
        Index(
            "ix_financial_receipts_credit_card_id",
            "credit_card_id",
        ),
        Index(
            "ix_financial_receipts_customer_id",
            "customer_id",
        ),
        Index(
            "ix_financial_receipts_tracking_number",
            "tracking_number",
        ),
        Index(
            "ix_financial_receipts_counterparty_name",
            "counterparty_name",
        ),
        Index(
            "ix_financial_receipts_direction",
            "direction",
        ),
        Index(
            "ix_financial_receipts_receipt_date",
            "receipt_date",
        ),
        Index(
            "ix_financial_receipts_currency_id",
            "currency_id",
        ),
        Index(
            "ix_financial_receipts_base_currency_id",
            "base_currency_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id"),
        nullable=False,
    )
    owner_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    credit_card_id = Column(
        Integer,
        ForeignKey("financial_cards.id"),
        nullable=False,
    )
    customer_id = Column(
        Integer,
        ForeignKey("financial_customers.id"),
        nullable=True,
    )
    description = Column(Text, nullable=False)
    description_embedding = Column(
        Vector(1024),
        nullable=True,
    )
    tracking_number = Column(
        String,
        nullable=True,
    )
    amount = Column(
        Numeric(14, 2),
        nullable=False,
    )

    currency = Column(
        String(12),
        nullable=False,
        default=FinancialCurrency.TOMAN.value,
        index=True,
    )
    base_currency = Column(
        String(12),
        nullable=False,
        default=FinancialCurrency.TOMAN.value,
        index=True,
    )
    exchange_rate_to_base = Column(
        Numeric(18, 6),
        nullable=False,
        default=1,
    )
    base_amount = Column(
        Numeric(18, 2),
        nullable=False,
        default=0,
    )
    exchange_rate_source = Column(
        String(20),
        nullable=False,
        default="system",
    )

    currency_id = Column(
        Integer,
        ForeignKey(
            "currencies.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    base_currency_id = Column(
        Integer,
        ForeignKey(
            "currencies.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    amount_base = Column(
        Numeric(28, 10),
        nullable=True,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=True,
    )

    direction = Column(
        String,
        nullable=False,
        index=True,
    )
    counterparty_name = Column(
        String,
        nullable=False,
        index=True,
    )
    receipt_date = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
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
    owner = relationship(
        "User",
        back_populates="financial_receipts",
    )
    credit_card = relationship(
        "FinancialCard",
        back_populates="receipts",
    )
    customer = relationship(
        "FinancialCustomer",
        back_populates="receipts",
    )
    canonical_currency = relationship(
        "Currency",
        foreign_keys=[currency_id],
    )
    canonical_base_currency = relationship(
        "Currency",
        foreign_keys=[base_currency_id],
    )
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
    purchase_cost_allocations = relationship(
        "PurchaseCostPaymentAllocation",
        back_populates="financial_receipt",
        passive_deletes=True,
        order_by=(
            "PurchaseCostPaymentAllocation."
            "created_at"
        ),
    )


class PurchaseCostPaymentAllocation(Base):
    __tablename__ = (
        "purchase_cost_payment_allocations"
    )
    __table_args__ = (
        CheckConstraint(
            "allocated_amount > 0",
            name="amount_positive",
        ),
        CheckConstraint(
            "allocated_amount_base > 0",
            name="amount_base_positive",
        ),
        CheckConstraint(
            "exchange_rate_used > 0",
            name="rate_positive",
        ),
        Index(
            (
                "ix_purchase_cost_payment_allocations_"
                "company_id"
            ),
            "company_id",
        ),
        Index(
            (
                "ix_purchase_cost_payment_allocations_"
                "financial_receipt_id"
            ),
            "financial_receipt_id",
        ),
        Index(
            (
                "ix_purchase_cost_payment_allocations_"
                "purchase_order_cost_id"
            ),
            "purchase_order_cost_id",
        ),
        Index(
            (
                "ix_purchase_cost_payment_allocations_"
                "currency_id"
            ),
            "currency_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    financial_receipt_id = Column(
        Integer,
        ForeignKey(
            "financial_receipts.id",
            name="fk_pcpa_receipt",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    purchase_order_cost_id = Column(
        Integer,
        ForeignKey(
            "purchase_order_costs.id",
            name="fk_pcpa_cost",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    allocated_amount = Column(
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
    allocated_amount_base = Column(
        Numeric(28, 10),
        nullable=False,
    )
    exchange_rate_used = Column(
        Numeric(28, 10),
        nullable=False,
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    financial_receipt = relationship(
        "FinancialReceipt",
        back_populates=(
            "purchase_cost_allocations"
        ),
    )
    company = relationship("Company")
    currency = relationship("Currency")
    created_by_user = relationship(
        "User",
        foreign_keys=[created_by_user_id],
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
