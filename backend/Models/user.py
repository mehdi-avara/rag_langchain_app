from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
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
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)
    notification_token = Column(String, nullable=True)
    image_path = Column(String, nullable=True)
    profile_asset_id = Column(Integer, ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True, index=True)

    company = relationship("Company", back_populates="users")
    profile_asset = relationship("FileAsset", foreign_keys=[profile_asset_id])

    roles = relationship("Role", secondary="user_role", back_populates="users", lazy="selectin")
    system_tags = relationship("SystemTag", back_populates="owner", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user")
    files = relationship("CommentFile", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    financial_cards = relationship("FinancialCard", back_populates="owner", cascade="all, delete-orphan")
    financial_customers = relationship("FinancialCustomer", back_populates="owner", cascade="all, delete-orphan")
    financial_receipts = relationship("FinancialReceipt", back_populates="owner", cascade="all, delete-orphan")
    warehouse_items = relationship("WarehouseItem", back_populates="owner", cascade="all, delete-orphan")
    owned_properties = relationship("OwnedProperty", back_populates="owner", cascade="all, delete-orphan")

    financial_receipt_files = relationship(
        "FinancialReceiptFile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
