from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from db.base import Base


class FileAssetStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class FileAsset(Base):
    __tablename__ = "file_assets"
    __table_args__ = (
        Index("ix_file_assets_company_id", "company_id"),
        Index("ix_file_assets_owner_id", "owner_id"),
        Index("ix_file_assets_status", "status"),
        Index("ix_file_assets_purpose", "purpose"),
        Index("ix_file_assets_storage_key", "storage_key"),
    )

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    original_filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    checksum = Column(String, nullable=True)

    bucket = Column(String, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)
    storage_backend = Column(String, nullable=False, default="s3")

    status = Column(String, nullable=False, default=FileAssetStatus.PENDING.value)
    purpose = Column(String, nullable=False, index=True)

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    owner = relationship("User", foreign_keys="FileAsset.owner_id")
    company = relationship("Company", foreign_keys="FileAsset.company_id")
