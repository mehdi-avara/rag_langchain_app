from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    First_name = Column(String, nullable=False)
    Last_name = Column(String, nullable=True)
    pw_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notification_token = Column(String, nullable=True)
    image_path = Column(String, nullable=True)

    company = relationship("Company", back_populates="users")

    roles = relationship("Role", secondary="user_role", back_populates="users", lazy="selectin")
    system_tags = relationship("SystemTag", back_populates="owner", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user")
    files = relationship("CommentFile", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    financial_cards = relationship("FinancialCard", back_populates="owner", cascade="all, delete-orphan")
    financial_receipts = relationship("FinancialReceipt", back_populates="owner", cascade="all, delete-orphan")

    financial_receipt_files = relationship(
        "FinancialReceiptFile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

