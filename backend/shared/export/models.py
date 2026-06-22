from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class ExportAuditLog(Base):
    __tablename__ = "export_audit_logs"
    __table_args__ = (
        Index("ix_export_audit_company_created", "company_id", "created_at"),
        Index("ix_export_audit_user_created", "requested_by_user_id", "created_at"),
        Index("ix_export_audit_module_entity", "module", "entity"),
        Index("ix_export_audit_status", "status"),
        Index("ix_export_audit_task_result_id", "task_result_id"),
        Index("ix_export_audit_file_asset_id", "file_asset_id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("task_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_asset_id = Column(
        Integer,
        ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    module = Column(String(80), nullable=False)
    entity = Column(String(80), nullable=False)
    export_format = Column(String(10), nullable=False)
    filters_json = Column(JSONB, nullable=False, default=dict)
    columns_json = Column(JSONB, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="pending")
    row_count = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    completed_at = Column(DateTime, nullable=True)
