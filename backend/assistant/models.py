"""Generic assistant persistence: ``Draft`` and ``AgentRun``.

These two tables are deliberately **module-agnostic** so other modules can reuse
the same draft-and-confirm machinery later. Nothing in here imports a domain
module's models.

Lifecycle rules (PROMPT §4.1):
- Per-object single-state: one ``Draft`` row / one ``AgentRun`` row is in exactly
  one status at a time.
- Per-conversation multi-machine: one ``chat_id`` owns N AgentRuns and M Drafts.
- Invariant (enforced in the runner): at most one ``active`` AgentRun per chat.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base


class DraftStatus(str, enum.Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentRunStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    WAITING_ON_TASK = "waiting_on_task"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentRun(Base):
    """A single agentic turn (master plan §12.8).

    Holds the resumable run status and a JSON snapshot of the graph state so a
    suspended / waiting_on_task run can resume from another device. This is
    machinery — never rendered to the user (the visible transcript is the
    ``ChatMessage`` rows).
    """

    __tablename__ = "assistant_agent_runs"
    __table_args__ = (
        Index("ix_assistant_agent_runs_chat_id", "chat_id"),
        Index("ix_assistant_agent_runs_company_id", "company_id"),
        Index("ix_assistant_agent_runs_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(20), nullable=False, default=AgentRunStatus.ACTIVE.value)
    intent = Column(String(64), nullable=True)
    language = Column(String(16), nullable=True)
    intake_mode = Column(String(16), nullable=True)  # inline | heavy | None
    task_id = Column(String(128), nullable=True)     # Celery task id when waiting_on_task
    error_code = Column(String(64), nullable=True)

    # JSON snapshot of AgentState (sanitised — no Session / User objects).
    state = Column(JSONB, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    drafts = relationship("Draft", back_populates="agent_run")


class Draft(Base):
    """A proposed, **uncommitted** write (PROMPT §4).

    The assistant never writes the domain entity. It assembles the payload and a
    ``commit_target`` (method + endpoint + permission) and the frontend POSTs the
    final payload to the module's own create/update route, then notifies the
    assistant via ``POST /assistant/drafts/{id}/committed`` (record-only).
    """

    __tablename__ = "assistant_drafts"
    __table_args__ = (
        Index("ix_assistant_drafts_chat_id", "chat_id"),
        Index("ix_assistant_drafts_company_id", "company_id"),
        Index("ix_assistant_drafts_created_by_user_id", "created_by_user_id"),
        Index("ix_assistant_drafts_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    agent_run_id = Column(Integer, ForeignKey("assistant_agent_runs.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    target_module = Column(String(64), nullable=False, default="financial_management")
    target_action = Column(String(64), nullable=False)  # create_receipt | update_receipt | ...

    payload = Column(JSONB, nullable=False, default=dict)        # proposed canonical fields
    commit_target = Column(JSONB, nullable=False, default=dict)  # {method, endpoint, permission}
    attachments = Column(JSONB, nullable=False, default=list)    # FileAsset ids
    validation = Column(JSONB, nullable=False, default=dict)     # per-field validation result

    language = Column(String(16), nullable=False, default="en")  # BCP-47
    status = Column(String(20), nullable=False, default=DraftStatus.PENDING.value)

    committed_entity_ref = Column(JSONB, nullable=True)  # set from the frontend committed-notification

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent_run = relationship("AgentRun", back_populates="drafts")
