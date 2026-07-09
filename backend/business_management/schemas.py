from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


FlowSource = Literal["record", "audit", "inferred"]
RootType = Literal["mr", "rfq", "po", "grn", "stock"]


class BusinessFlowRoot(BaseModel):
    type: RootType
    id: int


class BusinessFlowNode(BaseModel):
    id: str
    kind: str
    state: str
    title: str
    description: str | None = None
    source: FlowSource
    is_inferred: bool = False
    route: str | None = None
    actor_user_id: int | None = None
    created_at: datetime | None = None
    changed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BusinessFlowConnection(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    label: str | None = None
    source: FlowSource
    is_inferred: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class BusinessFlowTimelineEvent(BaseModel):
    id: str
    kind: str
    state: str
    title: str
    description: str | None = None
    source: FlowSource
    is_inferred: bool = False
    entity_type: str
    entity_id: int | None = None
    actor_user_id: int | None = None
    from_status: str | None = None
    to_status: str | None = None
    created_at: datetime | None = None
    changed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BusinessFlowResponse(BaseModel):
    root: BusinessFlowRoot
    audit_coverage: dict[str, str]
    nodes: list[BusinessFlowNode]
    connections: list[BusinessFlowConnection]
    timeline: list[BusinessFlowTimelineEvent]
