"""Pydantic request/response models for the assistant endpoints (PROMPT §4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssistantChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    chat_id: Optional[int] = None
    attachments: List[int] = Field(default_factory=list)  # FileAsset ids (§6)


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    agent_run_id: Optional[int] = None
    created_by_user_id: int
    company_id: int
    target_module: str
    target_action: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    commit_target: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Any] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    language: str = "en"
    status: str = "pending"
    committed_entity_ref: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class DraftPatchRequest(BaseModel):
    # User edits to the assistant-side copy before committing (optional, §4).
    payload: Optional[Dict[str, Any]] = None
    # Create-callback: the frontend created a previously-missing FK record (or picked
    # an alternative) and reports the chosen id back so the server writes it into the
    # payload and clears the pending reference (FK-resolution task).
    # shape: { "<field>": { "id": <int>, "label": "<optional str>" } }
    resolved_references: Optional[Dict[str, Dict[str, Any]]] = None


class DraftCommittedRequest(BaseModel):
    # Record-only notification: the frontend already wrote via the module endpoint.
    committed_entity_ref: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Module-independent assistant debug API
# ---------------------------------------------------------------------------


class DebugChatMetadata(BaseModel):
    id: int
    name: str
    company_id: int
    user_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DebugMessageOut(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    draft_id: Optional[int] = None
    created_at: Optional[datetime] = None


class TimelineItem(BaseModel):
    id: int
    agent_run_id: int
    message_id: Optional[int] = None
    sequence: int
    kind: str
    event_type: str
    stage: str
    module: Optional[str] = None
    task: Optional[str] = None
    title: str
    summary: str
    status: str
    severity: str
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AgentRunSummary(BaseModel):
    id: int
    chat_id: int
    input_message_id: Optional[int] = None
    output_message_id: Optional[int] = None
    company_id: int
    user_id: int
    status: str
    current_stage: Optional[str] = None
    intent: Optional[str] = None
    language: Optional[str] = None
    state: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    last_event_sequence: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class RunDebugOut(BaseModel):
    run: AgentRunSummary
    timeline: List[TimelineItem] = Field(default_factory=list)
    routing_decisions: List[TimelineItem] = Field(default_factory=list)
    drafts: List[DraftOut] = Field(default_factory=list)
    errors: List[TimelineItem] = Field(default_factory=list)
    final_output_message: Optional[DebugMessageOut] = None


class MessageRunDebugOut(BaseModel):
    message: DebugMessageOut
    run: Optional[RunDebugOut] = None


class ChatDebugOut(BaseModel):
    chat: DebugChatMetadata
    messages: List[MessageRunDebugOut] = Field(default_factory=list)
    runs: List[RunDebugOut] = Field(default_factory=list)
    unassociated_runs: List[RunDebugOut] = Field(default_factory=list)


class DebugMessagesResponse(BaseModel):
    chat: DebugChatMetadata
    messages: List[DebugMessageOut]
    limit: int
    offset: int


class RunEventsResponse(BaseModel):
    run_id: int
    after_sequence: int
    next_after_sequence: int
    has_more: bool
    events: List[TimelineItem]


class RunTimelineGroup(BaseModel):
    run: AgentRunSummary
    events: List[TimelineItem]


class ChatTimelineResponse(BaseModel):
    chat_id: int
    runs: List[RunTimelineGroup]


class RunStateResponse(BaseModel):
    run_id: int
    status: str
    current_stage: Optional[str] = None
    state: Optional[Dict[str, Any]] = None


class DebugTaskDescriptor(BaseModel):
    identifier: str
    kind: str
    description: str
    required_permission: Optional[str] = None


class DebugModuleDescriptor(BaseModel):
    identifier: str
    title: str
    description: str
    tasks: List[DebugTaskDescriptor] = Field(default_factory=list)


class DebugModulesResponse(BaseModel):
    modules: List[DebugModuleDescriptor]
