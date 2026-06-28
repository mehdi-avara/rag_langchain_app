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
