"""Task polling endpoint.

Frontend uses  GET /tasks/{task_id}  to check async task progress.

Response shape:
  {
    "task_id": "<uuid>",
    "task_type": "stt_transcription",
    "status": "pending" | "in_progress" | "success" | "failure",
    "result": { ... } | null,
    "error": "..." | null
  }

Polling strategy (recommended for frontend):
  - poll every 2 s while status is pending/in_progress
  - stop on success or failure
  - 60 s timeout → show error to user
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Any, Optional

from db.init_db import get_db
from deps import require_permission
from Models import User
from Models.task_result import TaskResult

router = APIRouter()


class TaskStatusResponse(BaseModel):
    task_id: str
    task_type: str
    status: str  # pending | in_progress | success | failure
    result: Optional[Any] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("stt:use")),
):
    """Poll an async task.  Returns 404 if the task_id is unknown or belongs
    to a different user (prevents enumeration)."""
    try:
        parsed_id = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    task: TaskResult | None = (
        db.query(TaskResult)
        .filter(
            TaskResult.id == parsed_id,
            TaskResult.created_by_user_id == current_user.id,
        )
        .first()
    )

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        result=task.result_json,
        error=task.error_message,
    )
