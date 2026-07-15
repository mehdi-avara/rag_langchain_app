"""Draft + AgentRun persistence service (PROMPT §4, §4.1, §8.1).

The assistant performs **no domain writes**. ``record_committed`` is record-only:
it sets ``status=committed`` and stores ``committed_entity_ref`` after the frontend
has already written via the module's own endpoint — it re-checks no domain
permission and creates/modifies no financial entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from Models import AgentRun, Draft, User
from Models.chat import ChatRole

from .errors import draft_not_found, draft_not_pending, permission_denied
from .models import AgentRunStatus, DraftStatus


# ---------------------------------------------------------------------------
# AgentRun lifecycle
# ---------------------------------------------------------------------------

def suspend_active_runs(db: Session, *, chat_id: int) -> None:
    """Enforce the invariant: at most one ``active`` run per conversation (§4.1)."""
    active_runs = (
        db.query(AgentRun)
        .filter(AgentRun.chat_id == chat_id, AgentRun.status == AgentRunStatus.ACTIVE.value)
        .all()
    )
    for run in active_runs:
        run.status = AgentRunStatus.SUSPENDED.value
    if active_runs:
        db.commit()


def create_agent_run(
    db: Session, *, chat_id: int, user: User, input_message_id: Optional[int] = None,
) -> AgentRun:
    suspend_active_runs(db, chat_id=chat_id)
    run = AgentRun(
        chat_id=chat_id,
        created_by_user_id=user.id,
        user_id=user.id,
        company_id=user.company_id,
        input_message_id=input_message_id,
        status=AgentRunStatus.ACTIVE.value,
        current_stage="starting",
        started_at=datetime.utcnow(),
        last_event_sequence=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run(
    db: Session,
    run: AgentRun,
    *,
    status: Optional[str] = None,
    intent: Optional[str] = None,
    language: Optional[str] = None,
    intake_mode: Optional[str] = None,
    task_id: Optional[str] = None,
    error_code: Optional[str] = None,
    state: Optional[dict] = None,
    current_stage: Optional[str] = None,
    output_message_id: Optional[int] = None,
    completed_at: Optional[datetime] = None,
) -> AgentRun:
    if status is not None:
        run.status = status
    if intent is not None:
        run.intent = intent
    if language is not None:
        run.language = language
    if intake_mode is not None:
        run.intake_mode = intake_mode
    if task_id is not None:
        run.task_id = task_id
    if error_code is not None:
        run.error_code = error_code
    if state is not None:
        run.state = state
    if current_stage is not None:
        run.current_stage = current_stage
    if output_message_id is not None:
        run.output_message_id = output_message_id
    if completed_at is not None:
        run.completed_at = completed_at
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Draft lifecycle
# ---------------------------------------------------------------------------

def persist_draft(
    db: Session,
    *,
    chat_id: int,
    agent_run_id: Optional[int],
    user: User,
    pending_draft: dict,
    language: str,
) -> Draft:
    """Persist a built-but-uncommitted draft (status=pending). Never writes domain data."""
    draft = Draft(
        chat_id=chat_id,
        agent_run_id=agent_run_id,
        created_by_user_id=user.id,
        company_id=user.company_id,
        target_module=pending_draft.get("target_module", "financial_management"),
        target_action=pending_draft["target_action"],
        payload=pending_draft.get("payload") or {},
        commit_target=pending_draft.get("commit_target") or {},
        attachments=pending_draft.get("attachments") or [],
        validation=pending_draft.get("validation") or {},
        language=language or "en",
        status=DraftStatus.PENDING.value,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_draft(db: Session, *, draft_id: int, user: User) -> Draft:
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if draft is None or draft.company_id != user.company_id:
        raise draft_not_found()
    if draft.created_by_user_id != user.id:
        # The caller must own the draft (PROMPT §10.6).
        raise permission_denied("assistant:draft")
    return draft


def patch_draft(
    db: Session,
    *,
    draft: Draft,
    payload: Optional[dict] = None,
    resolved_references: Optional[dict] = None,
) -> Draft:
    if draft.status != DraftStatus.PENDING.value:
        raise draft_not_pending()
    if payload is not None:
        merged = dict(draft.payload or {})
        merged.update(payload)
        draft.payload = merged
    if resolved_references:
        # Create-callback: the frontend created the missing record (or picked an
        # alternative) and reports the id back. Write it into the payload, flip the
        # matching reference to resolved, and drop it from references_pending.
        # NOTE: SQLAlchemy JSON columns only persist when REASSIGNED — always build a
        # new dict and reassign (do not mutate draft.payload / draft.validation in place).
        new_payload = dict(draft.payload or {})
        validation = dict(draft.validation or {})
        refs = list(validation.get("references") or [])
        pending = list(validation.get("references_pending") or [])
        for field_name, chosen in resolved_references.items():
            if not isinstance(chosen, dict) or "id" not in chosen:
                continue
            new_payload[field_name] = chosen["id"]
            for ref in refs:
                if ref.get("field") == field_name:
                    ref["status"] = "resolved"
                    ref["chosen"] = {"id": chosen["id"], "label": chosen.get("label")}
            pending = [f for f in pending if f != field_name]
        draft.payload = new_payload
        validation["references"] = refs
        validation["references_pending"] = pending
        draft.validation = validation
    db.commit()
    db.refresh(draft)
    return draft


def record_committed(db: Session, *, draft: Draft, user: User, committed_entity_ref: dict) -> Draft:
    """Record-only: the frontend already wrote via the module endpoint (§4.1).

    Does NOT create/modify any domain entity and re-checks no domain permission.
    """
    if draft.status != DraftStatus.PENDING.value:
        raise draft_not_pending()
    draft.status = DraftStatus.COMMITTED.value
    draft.committed_entity_ref = committed_entity_ref or {}
    db.commit()
    db.refresh(draft)
    return draft


def cancel_draft(db: Session, *, draft: Draft) -> Draft:
    if draft.status != DraftStatus.PENDING.value:
        raise draft_not_pending()
    draft.status = DraftStatus.CANCELLED.value
    db.commit()
    db.refresh(draft)
    return draft
