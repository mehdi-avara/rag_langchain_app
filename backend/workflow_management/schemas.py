from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .models import (
    WorkflowAssigneeType,
    WorkflowInstanceStatus,
    WorkflowStepInstanceStatus,
    WorkflowStepType,
    WorkflowVersionStatus,
)


def _required_text(value, field_name: str) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError(f"{field_name} is required")

    return normalized


def _optional_text(value):
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _validate_assignee_shape(values) -> None:
    target_fields = {
        WorkflowAssigneeType.USER: "target_user_id",
        WorkflowAssigneeType.DEPARTMENT: "target_department_id",
        WorkflowAssigneeType.POSITION: "target_position_id",
        WorkflowAssigneeType.ROLE: "target_role_id",
    }
    target_values = {
        "target_user_id": values.target_user_id,
        "target_department_id": values.target_department_id,
        "target_position_id": values.target_position_id,
        "target_role_id": values.target_role_id,
    }

    expected = target_fields.get(values.assignee_type)

    if expected is None:
        if any(value is not None for value in target_values.values()):
            raise ValueError(
                "requester and any assignees cannot have a target ID"
            )
        return

    if target_values[expected] is None:
        raise ValueError(
            f"{expected} is required for {values.assignee_type.value}"
        )

    unexpected = [
        field
        for field, value in target_values.items()
        if field != expected and value is not None
    ]

    if unexpected:
        raise ValueError(
            "Only the target matching assignee_type may be provided"
        )


class WorkflowDefinitionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    entity_type: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return _required_text(value, "code").upper()

    @field_validator("name", "entity_type", mode="before")
    @classmethod
    def normalize_required_text(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type(cls, value):
        return value.lower()

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)


class WorkflowDefinitionUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=80)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    entity_type: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        return _required_text(value, "code").upper()

    @field_validator("name", "entity_type", mode="before")
    @classmethod
    def normalize_required_text(cls, value, info):
        if value is None:
            return None
        return _required_text(value, info.field_name)

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type(cls, value):
        return value.lower() if value is not None else None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)


class WorkflowDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    name: str
    entity_type: str
    description: Optional[str]
    is_active: bool
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class WorkflowVersionCreate(BaseModel):
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _optional_text(value)


class WorkflowVersionUpdate(BaseModel):
    notes: Optional[str] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        return _optional_text(value)


class WorkflowVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_definition_id: int
    version_number: int
    status: WorkflowVersionStatus
    notes: Optional[str]
    created_by_user_id: Optional[int]
    published_by_user_id: Optional[int]
    published_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class WorkflowStepCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    step_type: WorkflowStepType = WorkflowStepType.APPROVAL
    sort_order: int = Field(0, ge=0)
    is_start: bool = False
    is_terminal: bool = False
    assignee_type: WorkflowAssigneeType = WorkflowAssigneeType.ANY
    target_user_id: Optional[int] = Field(None, gt=0)
    target_department_id: Optional[int] = Field(None, gt=0)
    target_position_id: Optional[int] = Field(None, gt=0)
    target_role_id: Optional[int] = Field(None, gt=0)
    required_approval_count: int = Field(1, ge=1)
    due_in_hours: Optional[int] = Field(None, gt=0)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return _required_text(value, "code").upper()

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return _required_text(value, "name")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)

    @model_validator(mode="after")
    def validate_step(self):
        _validate_assignee_shape(self)

        if self.step_type == WorkflowStepType.END:
            if not self.is_terminal:
                raise ValueError("end steps must be terminal")
            if self.assignee_type != WorkflowAssigneeType.ANY:
                raise ValueError("end steps must use the any assignee")
        elif self.is_terminal:
            raise ValueError("only end steps may be terminal")

        return self


class WorkflowStepUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=80)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    step_type: Optional[WorkflowStepType] = None
    sort_order: Optional[int] = Field(None, ge=0)
    is_start: Optional[bool] = None
    is_terminal: Optional[bool] = None
    assignee_type: Optional[WorkflowAssigneeType] = None
    target_user_id: Optional[int] = Field(None, gt=0)
    target_department_id: Optional[int] = Field(None, gt=0)
    target_position_id: Optional[int] = Field(None, gt=0)
    target_role_id: Optional[int] = Field(None, gt=0)
    required_approval_count: Optional[int] = Field(None, ge=1)
    due_in_hours: Optional[int] = Field(None, gt=0)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        return _required_text(value, "code").upper()

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if value is None:
            return None
        return _required_text(value, "name")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)


class WorkflowStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_version_id: int
    code: str
    name: str
    description: Optional[str]
    step_type: WorkflowStepType
    sort_order: int
    is_start: bool
    is_terminal: bool
    assignee_type: WorkflowAssigneeType
    target_user_id: Optional[int]
    target_department_id: Optional[int]
    target_position_id: Optional[int]
    target_role_id: Optional[int]
    required_approval_count: int
    due_in_hours: Optional[int]
    created_at: datetime
    updated_at: datetime


class WorkflowTransitionCreate(BaseModel):
    from_step_id: int = Field(..., gt=0)
    to_step_id: int = Field(..., gt=0)
    action_key: str = Field(..., min_length=1, max_length=80)
    action_label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    require_comment: bool = False

    @field_validator("action_key", mode="before")
    @classmethod
    def normalize_action_key(cls, value):
        return _required_text(value, "action_key").lower()

    @field_validator("action_label", mode="before")
    @classmethod
    def normalize_action_label(cls, value):
        return _required_text(value, "action_label")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)

    @model_validator(mode="after")
    def validate_steps(self):
        if self.from_step_id == self.to_step_id:
            raise ValueError("from_step_id and to_step_id must differ")
        return self


class WorkflowTransitionUpdate(BaseModel):
    from_step_id: Optional[int] = Field(None, gt=0)
    to_step_id: Optional[int] = Field(None, gt=0)
    action_key: Optional[str] = Field(None, min_length=1, max_length=80)
    action_label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    require_comment: Optional[bool] = None

    @field_validator("action_key", mode="before")
    @classmethod
    def normalize_action_key(cls, value):
        if value is None:
            return None
        return _required_text(value, "action_key").lower()

    @field_validator("action_label", mode="before")
    @classmethod
    def normalize_action_label(cls, value):
        if value is None:
            return None
        return _required_text(value, "action_label")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value):
        return _optional_text(value)


class WorkflowTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_version_id: int
    from_step_id: int
    to_step_id: int
    action_key: str
    action_label: str
    description: Optional[str]
    require_comment: bool
    created_at: datetime
    updated_at: datetime


class WorkflowInstanceCreate(BaseModel):
    workflow_definition_id: int = Field(..., gt=0)
    workflow_version_id: Optional[int] = Field(None, gt=0)
    entity_type: str = Field(..., min_length=1, max_length=80)
    entity_id: str = Field(..., min_length=1, max_length=120)
    title: Optional[str] = Field(None, max_length=255)
    context_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_type", "entity_id", mode="before")
    @classmethod
    def normalize_required_text(cls, value, info):
        return _required_text(value, info.field_name)

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type(cls, value):
        return value.lower()

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return _optional_text(value)


class WorkflowActionCreate(BaseModel):
    action_key: str = Field(..., min_length=1, max_length=80)
    comment: Optional[str] = None

    @field_validator("action_key", mode="before")
    @classmethod
    def normalize_action_key(cls, value):
        return _required_text(value, "action_key").lower()

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value):
        return _optional_text(value)


class WorkflowCancelCreate(BaseModel):
    reason: Optional[str] = None

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value):
        return _optional_text(value)


class WorkflowStepInstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_instance_id: int
    step_definition_id: int
    sequence_number: int
    status: WorkflowStepInstanceStatus
    assignee_type: WorkflowAssigneeType
    assigned_user_id: Optional[int]
    assigned_department_id: Optional[int]
    assigned_position_id: Optional[int]
    assigned_role_id: Optional[int]
    started_at: Optional[datetime]
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    outcome: Optional[str]
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime


class WorkflowInstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    workflow_definition_id: int
    workflow_version_id: int
    current_step_definition_id: Optional[int]
    entity_type: str
    entity_id: str
    title: Optional[str]
    status: WorkflowInstanceStatus
    context_json: dict[str, Any]
    started_by_user_id: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    step_instances: list[WorkflowStepInstanceRead] = Field(
        default_factory=list
    )


class WorkflowFileCreate(BaseModel):
    file_asset_id: int = Field(..., gt=0)
    step_instance_id: Optional[int] = Field(None, gt=0)
    label: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None

    @field_validator("label", "description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        return _optional_text(value)


class WorkflowFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    workflow_instance_id: int
    step_instance_id: Optional[int]
    file_asset_id: int
    attached_by_user_id: Optional[int]
    label: Optional[str]
    description: Optional[str]
    created_at: datetime


class WorkflowAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    workflow_instance_id: int
    step_instance_id: Optional[int]
    actor_user_id: Optional[int]
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    action_key: Optional[str]
    message: Optional[str]
    details_json: dict[str, Any]
    created_at: datetime
