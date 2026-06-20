"""Persistent task result store for async Celery operations.

Every 202-response endpoint creates a TaskResult row so the frontend can poll
GET /tasks/{task_id} for completion status and result data.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from db.base import Base


class TaskResult(Base):
    __tablename__ = "task_results"

    # ── Identity ──────────────────────────────────────────────────────────────
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Celery's own task id (set right after dispatch, may be NULL for a moment)
    celery_task_id = Column(String(255), nullable=True, index=True)

    # ── Classification ────────────────────────────────────────────────────────
    task_type = Column(String(60), nullable=False, index=True)

    # ── State machine ─────────────────────────────────────────────────────────
    # pending → in_progress → success | failure
    status = Column(String(20), nullable=False, default="pending", index=True)

    # ── Payload ───────────────────────────────────────────────────────────────
    result_json = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskResult id={self.id} type={self.task_type} status={self.status}>"
