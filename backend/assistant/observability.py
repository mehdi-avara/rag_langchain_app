"""Append-only assistant execution events and company-scoped debug reads."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from time import perf_counter
from typing import Any, Iterable

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from Models import AgentRun, AssistantEvent, Chat, ChatMessage, Draft, User

from .errors import message_not_found, run_not_found
from .models import AgentRunStatus
from .redaction import sanitize_event_payload, sanitize_payload
from settings import get_settings


logger = logging.getLogger("assistant.observability")
TERMINAL_RUN_STATUSES = {
    AgentRunStatus.COMPLETED.value,
    AgentRunStatus.CANCELLED.value,
    AgentRunStatus.FAILED.value,
}
_execution_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "assistant_execution_context", default=None,
)


@contextmanager
def execution_context(*, db: Session, run: AgentRun, selected_module: str, selected_task: str):
    context = {
        "db": db, "run": run, "selected_module": selected_module,
        "selected_task": selected_task, "searched_modules": set(),
    }
    token = _execution_context.set(context)
    try:
        yield context
    finally:
        _execution_context.reset(token)


def current_execution_context() -> dict[str, Any] | None:
    return _execution_context.get()


def duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def prompt_hash(messages: list[dict] | None) -> str | None:
    if not messages:
        return None
    canonical = json.dumps(sanitize_payload(messages, max_bytes=256 * 1024), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _allocate_sequence(db: Session, run: AgentRun) -> int:
    """Allocate a run-local sequence atomically on PostgreSQL.

    The UPDATE takes a row lock and RETURNING supplies the exact value used by
    the subsequent event insert in the same transaction. The small fallback is
    for the repository's in-memory unit-test session only.
    """
    if hasattr(db, "execute"):
        statement = (
            update(AgentRun)
            .where(AgentRun.id == run.id, AgentRun.company_id == run.company_id)
            .values(last_event_sequence=func.coalesce(AgentRun.last_event_sequence, 0) + 1)
            .returning(AgentRun.last_event_sequence)
        )
        sequence = db.execute(statement).scalar_one_or_none()
        if sequence is None:
            raise run_not_found()
        run.last_event_sequence = sequence
        return int(sequence)
    sequence = int(getattr(run, "last_event_sequence", 0) or 0) + 1
    run.last_event_sequence = sequence
    return sequence


def _log_event(event: AssistantEvent, *, request_id: str | None = None) -> None:
    context = {
        "request_id": request_id,
        "chat_id": event.chat_id,
        "message_id": event.message_id,
        "agent_run_id": event.agent_run_id,
        "event_sequence": event.sequence,
        "company_id": event.company_id,
        "user_id": event.user_id,
        "stage": event.stage,
        "selected_module": event.selected_module,
        "selected_task": event.selected_task,
        "event_type": event.event_type,
        "status": event.status,
        "duration_ms": event.duration_ms,
        "error_code": event.error_code,
    }
    logger.log(
        logging.ERROR if event.severity == "error" else logging.WARNING if event.severity == "warning" else logging.INFO,
        event.event_type,
        extra={key: value for key, value in context.items() if value is not None},
    )


def record_event(
    db: Session,
    run: AgentRun,
    *,
    event_type: str,
    stage: str,
    status: str = "completed",
    severity: str = "info",
    message_id: int | None = None,
    selected_module: str | None = None,
    selected_task: str | None = None,
    route_from: str | None = None,
    route_to: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    request_id: str | None = None,
) -> AssistantEvent:
    """Insert one immutable event. No update/delete counterpart exists."""
    try:
        sequence = _allocate_sequence(db, run)
        event = AssistantEvent(
            chat_id=run.chat_id,
            agent_run_id=run.id,
            message_id=message_id if message_id is not None else run.input_message_id,
            company_id=run.company_id,
            user_id=run.user_id or run.created_by_user_id,
            sequence=sequence,
            event_type=event_type,
            stage=stage,
            status=status,
            severity=severity,
            selected_module=selected_module,
            selected_task=selected_task,
            route_from=route_from,
            route_to=route_to,
            payload=sanitize_event_payload(payload or {}),
            duration_ms=duration_ms,
            error_code=error_code,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        logger.exception(
            "assistant event persistence failed",
            extra={
                "agent_run_id": getattr(run, "id", None),
                "chat_id": getattr(run, "chat_id", None),
                "company_id": getattr(run, "company_id", None),
                "event_type": event_type,
                "stage": stage,
            },
        )
        raise
    _log_event(event, request_id=request_id)
    return event


def _snapshot(value: dict | None) -> dict | None:
    if value is None:
        return None
    safe = sanitize_payload(value, max_bytes=get_settings().assistant_state_snapshot_max_bytes)
    return safe if isinstance(safe, dict) else {"value": safe}


def start_step(
    db: Session,
    run: AgentRun,
    *,
    stage: str,
    event_type: str | None = None,
    state: dict | None = None,
    payload: dict | None = None,
) -> AssistantEvent:
    run.current_stage = stage
    if state is not None:
        run.state = _snapshot(state)
    return record_event(
        db, run, event_type=event_type or f"{stage}.started", stage=stage,
        status="started", payload=payload,
    )


def complete_step(
    db: Session,
    run: AgentRun,
    *,
    stage: str,
    event_type: str | None = None,
    state: dict | None = None,
    payload: dict | None = None,
    elapsed_ms: int | None = None,
) -> AssistantEvent:
    run.current_stage = stage
    if state is not None:
        run.state = _snapshot(state)
    return record_event(
        db, run, event_type=event_type or f"{stage}.completed", stage=stage,
        status="completed", payload=payload, duration_ms=elapsed_ms,
    )


def fail_step(
    db: Session,
    run: AgentRun,
    *,
    stage: str,
    error_code: str,
    event_type: str | None = None,
    state: dict | None = None,
    elapsed_ms: int | None = None,
) -> AssistantEvent:
    run.current_stage = stage
    run.error_code = error_code
    if state is not None:
        run.state = _snapshot(state)
    return record_event(
        db, run, event_type=event_type or f"{stage}.failed", stage=stage,
        status="failed", severity="error", duration_ms=elapsed_ms, error_code=error_code,
    )


def record_route(
    db: Session,
    run: AgentRun,
    *,
    event_type: str,
    stage: str,
    route_from: str,
    route_to: str,
    selected_module: str | None = None,
    selected_task: str | None = None,
    confidence: float | None = None,
    allowed_candidates: Iterable[str] = (),
    decision_summary: str,
    elapsed_ms: int | None = None,
) -> AssistantEvent:
    return record_event(
        db, run,
        event_type=event_type, stage=stage, status="completed",
        selected_module=selected_module, selected_task=selected_task,
        route_from=route_from, route_to=route_to, duration_ms=elapsed_ms,
        payload={
            "confidence": confidence,
            "allowed_candidates": list(allowed_candidates),
            "decision_summary": decision_summary[:512],
        },
    )


def record_model_call(
    db: Session,
    run: AgentRun,
    *,
    stage: str,
    status: str,
    provider: str,
    model: str,
    attempt: int = 1,
    elapsed_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    prompt_version: str | None = None,
    prompt_digest: str | None = None,
    response_format: str | None = None,
    error_code: str | None = None,
) -> AssistantEvent:
    return record_event(
        db, run, event_type=f"model.{status}", stage=stage, status=status,
        severity="error" if status == "failed" else "info", duration_ms=elapsed_ms,
        error_code=error_code,
        payload={
            "provider": provider, "model": model, "attempt": attempt,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": total_tokens, "prompt_version": prompt_version,
            "prompt_hash": prompt_digest, "response_format": response_format,
        },
    )


def record_tool_call(
    db: Session,
    run: AgentRun,
    *,
    stage: str,
    status: str,
    tool_identifier: str,
    owning_module: str,
    operation: str,
    elapsed_ms: int | None = None,
    input_summary: dict | None = None,
    output_summary: dict | None = None,
    error_code: str | None = None,
    produced_draft: bool = False,
    searched_another_module: bool = False,
) -> AssistantEvent:
    return record_event(
        db, run, event_type=f"tool.{status}", stage=stage, status=status,
        severity="error" if status == "failed" else "info", duration_ms=elapsed_ms,
        selected_module=owning_module, selected_task=operation, error_code=error_code,
        payload={
            "tool_identifier": tool_identifier,
            "owning_module": owning_module,
            "operation": operation,
            "input_summary": input_summary or {},
            "output_summary": output_summary or {},
            "produced_draft": produced_draft,
            "searched_another_module": searched_another_module,
        },
    )


def list_run_events(
    db: Session, *, run_id: int, company_id: int, after_sequence: int = 0, limit: int = 100,
) -> list[AssistantEvent]:
    return (
        db.query(AssistantEvent)
        .filter(
            AssistantEvent.agent_run_id == run_id,
            AssistantEvent.company_id == company_id,
            AssistantEvent.sequence > after_sequence,
        )
        .order_by(AssistantEvent.sequence.asc())
        .limit(min(max(limit, 1), 200))
        .all()
    )


def event_to_timeline(event: AssistantEvent) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.route_from or event.route_to:
        kind = "route"
    elif event.event_type.startswith("model."):
        kind = "model"
    elif event.event_type.startswith("tool.") or event.event_type.startswith("cross_module_search."):
        kind = "tool"
    elif "draft" in event.event_type:
        kind = "draft"
    elif event.event_type.startswith("validator."):
        kind = "validation"
    elif event.severity == "error" or event.status == "failed":
        kind = "error"
    elif event.event_type.startswith("answer."):
        kind = "answer"
    else:
        kind = "stage"
    title = event.event_type.replace("_", " ").replace(".", " · ").title()
    summary = payload.get("decision_summary")
    if not isinstance(summary, str):
        if event.route_to:
            summary = f"{event.route_from or 'route'} → {event.route_to}"
        elif event.error_code:
            summary = f"Failed with {event.error_code}"
        elif payload.get("tool_identifier"):
            summary = str(payload["tool_identifier"])
        else:
            summary = event.event_type.replace("_", " ").replace(".", " ")
    return {
        "id": event.id,
        "agent_run_id": event.agent_run_id,
        "message_id": event.message_id,
        "sequence": event.sequence,
        "kind": kind,
        "event_type": event.event_type,
        "stage": event.stage,
        "module": event.selected_module,
        "task": event.selected_task,
        "title": title,
        "summary": summary[:512],
        "status": event.status,
        "severity": event.severity,
        "duration_ms": event.duration_ms,
        "error_code": event.error_code,
        "data": payload,
        "created_at": event.created_at,
    }


def get_run(db: Session, *, run_id: int, company_id: int) -> AgentRun:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.company_id == company_id).first()
    if run is None:
        raise run_not_found()
    return run


def get_message_run(db: Session, *, message_id: int, company_id: int) -> AgentRun:
    message = (
        db.query(ChatMessage)
        .join(Chat, Chat.id == ChatMessage.chat_id)
        .filter(ChatMessage.id == message_id, Chat.company_id == company_id)
        .first()
    )
    if message is None:
        raise message_not_found()
    run = (
        db.query(AgentRun)
        .filter(AgentRun.input_message_id == message_id, AgentRun.company_id == company_id)
        .order_by(AgentRun.id.desc())
        .first()
    )
    if run is None:
        raise run_not_found()
    return run


def get_chat(db: Session, *, chat_id: int, company_id: int) -> Chat:
    from core.exceptions import chat_not_found_exception

    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.company_id == company_id).first()
    if chat is None:
        raise chat_not_found_exception()
    return chat


def get_run_debug_view(
    db: Session, *, run_id: int, company_id: int, event_limit: int = 200,
) -> dict[str, Any]:
    run = get_run(db, run_id=run_id, company_id=company_id)
    events = list_run_events(db, run_id=run.id, company_id=company_id, limit=event_limit)
    drafts = (
        db.query(Draft)
        .filter(Draft.agent_run_id == run.id, Draft.company_id == company_id)
        .order_by(Draft.id.asc())
        .all()
    )
    output = None
    if run.output_message_id is not None:
        output = (
            db.query(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .filter(ChatMessage.id == run.output_message_id, Chat.company_id == company_id)
            .first()
        )
    return {"run": run, "events": events, "drafts": drafts, "output_message": output}


def get_chat_debug_view(
    db: Session, *, chat_id: int, company_id: int,
    message_limit: int = 200, run_limit: int = 100, event_limit: int = 100,
) -> dict[str, Any]:
    chat = get_chat(db, chat_id=chat_id, company_id=company_id)
    messages = (
        db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.id.asc()).limit(min(max(message_limit, 1), 200)).all()
    )
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.chat_id == chat.id, AgentRun.company_id == company_id)
        .order_by(AgentRun.id.asc()).limit(min(max(run_limit, 1), 100)).all()
    )
    run_views = [
        get_run_debug_view(db, run_id=run.id, company_id=company_id, event_limit=event_limit)
        for run in runs
    ]
    return {"chat": chat, "messages": messages, "runs": run_views}


def mark_run_completed(run: AgentRun, *, output_message_id: int | None = None) -> None:
    run.status = AgentRunStatus.COMPLETED.value
    run.current_stage = "completed"
    run.completed_at = datetime.utcnow()
    if output_message_id is not None:
        run.output_message_id = output_message_id
