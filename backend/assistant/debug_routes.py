"""Permission-protected, company-scoped assistant debugging endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from Models import AgentRun, AssistantEvent, ChatMessage, Draft, User
from db.init_db import get_db
from deps import require_permission

from . import observability, registry
from .errors import permission_denied
from .schemas import (
    AgentRunSummary,
    ChatDebugOut,
    ChatTimelineResponse,
    DebugChatMetadata,
    DebugMessageOut,
    DebugMessagesResponse,
    DebugModuleDescriptor,
    DebugModulesResponse,
    DebugTaskDescriptor,
    DraftOut,
    MessageRunDebugOut,
    RunDebugOut,
    RunEventsResponse,
    RunStateResponse,
    RunTimelineGroup,
    TimelineItem,
)


router = APIRouter(prefix="/debug", tags=["assistant-debug"])


def _company_id(user: User) -> int:
    if user.company_id is None:
        raise permission_denied("assistant:debug")
    return user.company_id


def _message_out(message: ChatMessage | None) -> DebugMessageOut | None:
    if message is None:
        return None
    role = getattr(message.role, "value", str(message.role))
    return DebugMessageOut(
        id=message.id, chat_id=message.chat_id, role=role, content=message.content,
        draft_id=message.draft_id, created_at=message.created_at,
    )


def _run_summary(run: AgentRun) -> AgentRunSummary:
    return AgentRunSummary(
        id=run.id,
        chat_id=run.chat_id,
        input_message_id=run.input_message_id,
        output_message_id=run.output_message_id,
        company_id=run.company_id,
        user_id=run.user_id or run.created_by_user_id,
        status=run.status,
        current_stage=run.current_stage,
        intent=run.intent,
        language=run.language,
        state=run.state if isinstance(run.state, dict) else None,
        error_code=run.error_code,
        last_event_sequence=run.last_event_sequence or 0,
        started_at=run.started_at or run.created_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _timeline(events) -> list[TimelineItem]:
    return [TimelineItem.model_validate(observability.event_to_timeline(event)) for event in events]


def _run_debug(view: dict) -> RunDebugOut:
    timeline = _timeline(view["events"])
    return RunDebugOut(
        run=_run_summary(view["run"]),
        timeline=timeline,
        routing_decisions=[item for item in timeline if item.kind == "route"],
        drafts=[DraftOut.model_validate(draft) for draft in view["drafts"]],
        errors=[item for item in timeline if item.severity == "error" or item.status == "failed"],
        final_output_message=_message_out(view["output_message"]),
    )


def _chat_metadata(chat) -> DebugChatMetadata:
    return DebugChatMetadata(
        id=chat.id, name=chat.name, company_id=chat.company_id, user_id=chat.user_id,
        created_at=chat.created_at, updated_at=chat.updated_at,
    )


@router.get("/chats/{chat_id}", response_model=ChatDebugOut)
def get_chat_debug(
    chat_id: int,
    message_limit: int = Query(100, ge=1, le=200),
    run_limit: int = Query(50, ge=1, le=100),
    event_limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    view = observability.get_chat_debug_view(
        db, chat_id=chat_id, company_id=_company_id(current_user),
        message_limit=message_limit, run_limit=run_limit, event_limit=event_limit,
    )
    runs = [_run_debug(run_view) for run_view in view["runs"]]
    by_input_message = {
        item.run.input_message_id: item for item in runs if item.run.input_message_id is not None
    }
    messages = [
        MessageRunDebugOut(message=_message_out(message), run=by_input_message.get(message.id))
        for message in view["messages"]
    ]
    associated_ids = set(by_input_message)
    return ChatDebugOut(
        chat=_chat_metadata(view["chat"]), messages=messages, runs=runs,
        unassociated_runs=[item for item in runs if item.run.input_message_id not in associated_ids],
    )


@router.get("/chats/{chat_id}/messages", response_model=DebugMessagesResponse)
def get_chat_messages(
    chat_id: int,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    chat = observability.get_chat(db, chat_id=chat_id, company_id=company_id)
    messages = (
        db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.id.asc()).offset(offset).limit(limit).all()
    )
    return DebugMessagesResponse(
        chat=_chat_metadata(chat), messages=[_message_out(item) for item in messages],
        limit=limit, offset=offset,
    )


@router.get("/chats/{chat_id}/timeline", response_model=ChatTimelineResponse)
def get_chat_timeline(
    chat_id: int,
    run_limit: int = Query(50, ge=1, le=100),
    event_limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    observability.get_chat(db, chat_id=chat_id, company_id=company_id)
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.chat_id == chat_id, AgentRun.company_id == company_id)
        .order_by(AgentRun.id.asc()).limit(run_limit).all()
    )
    # Timelines remain grouped per initiating run; they are never flattened.
    groups = []
    for run in runs:
        events = observability.list_run_events(
            db, run_id=run.id, company_id=company_id, limit=event_limit,
        )
        groups.append(RunTimelineGroup(run=_run_summary(run), events=_timeline(events)))
    return ChatTimelineResponse(chat_id=chat_id, runs=groups)


@router.get("/chats/{chat_id}/stream")
def stream_chat_timeline(
    chat_id: int,
    after_event_id: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    """SSE tail of new events; each item retains its run id and run-local sequence."""
    company_id = _company_id(current_user)
    observability.get_chat(db, chat_id=chat_id, company_id=company_id)

    async def generate():
        cursor = after_event_id
        idle_ticks = 0
        while True:
            rows = (
                db.query(AssistantEvent)
                .filter(
                    AssistantEvent.chat_id == chat_id,
                    AssistantEvent.company_id == company_id,
                    AssistantEvent.id > cursor,
                )
                .order_by(AssistantEvent.id.asc()).limit(100).all()
            )
            if rows:
                idle_ticks = 0
                for row in rows:
                    cursor = row.id
                    data = observability.event_to_timeline(row)
                    yield "event: assistant_event\ndata: " + json.dumps(data, default=str) + "\n\n"
            else:
                idle_ticks += 1
                if idle_ticks >= 15:
                    idle_ticks = 0
                    yield f"event: heartbeat\ndata: {{\"after_event_id\": {cursor}}}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/messages/{message_id}/run", response_model=RunDebugOut)
def get_message_run(
    message_id: int,
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    run = observability.get_message_run(db, message_id=message_id, company_id=company_id)
    return _run_debug(observability.get_run_debug_view(db, run_id=run.id, company_id=company_id))


@router.get("/runs/{run_id}", response_model=RunDebugOut)
def get_run_debug(
    run_id: int,
    event_limit: int = Query(200, ge=1, le=200),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    return _run_debug(observability.get_run_debug_view(
        db, run_id=run_id, company_id=_company_id(current_user), event_limit=event_limit,
    ))


@router.get("/runs/{run_id}/events", response_model=RunEventsResponse)
def get_run_events(
    run_id: int,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    observability.get_run(db, run_id=run_id, company_id=company_id)
    rows = observability.list_run_events(
        db, run_id=run_id, company_id=company_id,
        after_sequence=after_sequence, limit=limit + 1,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    events = _timeline(rows)
    return RunEventsResponse(
        run_id=run_id, after_sequence=after_sequence,
        next_after_sequence=events[-1].sequence if events else after_sequence,
        has_more=has_more, events=events,
    )


@router.get("/runs/{run_id}/routes", response_model=list[TimelineItem])
def get_run_routes(
    run_id: int,
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    observability.get_run(db, run_id=run_id, company_id=company_id)
    events = observability.list_run_events(db, run_id=run_id, company_id=company_id, limit=limit)
    return [item for item in _timeline(events) if item.kind == "route"]


@router.get("/runs/{run_id}/state", response_model=RunStateResponse)
def get_run_state(
    run_id: int,
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    run = observability.get_run(db, run_id=run_id, company_id=_company_id(current_user))
    return RunStateResponse(
        run_id=run.id, status=run.status, current_stage=run.current_stage,
        state=run.state if isinstance(run.state, dict) else None,
    )


@router.get("/runs/{run_id}/drafts", response_model=list[DraftOut])
def get_run_drafts(
    run_id: int,
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(require_permission("assistant:debug")),
    db: Session = Depends(get_db),
):
    company_id = _company_id(current_user)
    observability.get_run(db, run_id=run_id, company_id=company_id)
    drafts = (
        db.query(Draft).filter(Draft.agent_run_id == run_id, Draft.company_id == company_id)
        .order_by(Draft.id.asc()).limit(limit).all()
    )
    return [DraftOut.model_validate(draft) for draft in drafts]


@router.get("/modules", response_model=DebugModulesResponse)
def get_debug_modules(
    current_user: User = Depends(require_permission("assistant:debug")),
):
    _company_id(current_user)
    modules = []
    for toolset in sorted(registry.all_toolsets(), key=lambda item: item.module):
        descriptor = toolset.module_descriptor()
        modules.append(DebugModuleDescriptor(
            identifier=descriptor.module,
            title=descriptor.display_title,
            description=descriptor.description,
            tasks=[
                DebugTaskDescriptor(
                    identifier=task.intent, kind=task.kind, description=task.description,
                    required_permission=task.required_permission,
                )
                for task in toolset.task_descriptors()
            ],
        ))
    return DebugModulesResponse(modules=modules)
