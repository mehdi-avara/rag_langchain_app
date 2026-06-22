from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from Models import TaskResult, User
from core.celery.celery_app import celery_app
from core.exceptions.error_codes import (
    EXPORT_INVALID_REQUEST,
    EXPORT_QUEUE_FAILED,
)

from .datasets import (
    ExportValidationError,
    get_dataset,
    normalize_filters,
    resolve_columns,
)
from .models import ExportAuditLog
from .schemas import ExportRequest, ExportTaskOut


def _raise(status_code: int, code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def queue_export(
    db: Session,
    current_user: User,
    module: str,
    entity: str,
    payload: ExportRequest,
) -> ExportTaskOut:
    if current_user.company_id is None:
        _raise(
            status.HTTP_403_FORBIDDEN,
            EXPORT_INVALID_REQUEST,
            "Current user does not belong to a company",
        )

    try:
        get_dataset(module, entity)
        filters = normalize_filters(module, entity, payload.filters)
        columns = resolve_columns(module, entity, payload.columns)
    except ExportValidationError as exc:
        _raise(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            EXPORT_INVALID_REQUEST,
            str(exc),
        )

    task = TaskResult(
        id=uuid.uuid4(),
        task_type=f"export:{module}:{entity}",
        status="pending",
        created_by_user_id=current_user.id,
    )
    audit = ExportAuditLog(
        company_id=current_user.company_id,
        requested_by_user_id=current_user.id,
        task_result_id=task.id,
        module=module,
        entity=entity,
        export_format=payload.format.value,
        filters_json=filters,
        columns_json=columns,
        status="pending",
    )

    db.add(task)
    db.add(audit)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _raise(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            EXPORT_QUEUE_FAILED,
            "Export task could not be prepared",
        )

    try:
        dispatched = celery_app.send_task(
            "shared.export.tasks.generate_export",
            args=[str(task.id), audit.id, current_user.id],
        )
    except Exception as exc:
        task.status = "failure"
        task.error_message = str(exc)
        audit.status = "failure"
        audit.error_message = str(exc)
        db.commit()
        _raise(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            EXPORT_QUEUE_FAILED,
            "Export task could not be queued",
        )

    task.celery_task_id = dispatched.id
    db.commit()

    return ExportTaskOut(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        audit_id=audit.id,
    )
