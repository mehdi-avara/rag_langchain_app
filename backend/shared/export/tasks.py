from __future__ import annotations

import logging

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import DBAPIError, OperationalError
from datetime import datetime
from pathlib import Path
from uuid import UUID

from core.celery.celery_app import celery_app
from db.session import db_session
from Models import TaskResult, User
from settings import get_settings
from storage.manager import StorageManager

from .datasets import (
    column_labels,
    fetch_export_rows,
    get_dataset,
    resolve_columns,
)
from .models import ExportAuditLog
from .renderers import render_export


logger = logging.getLogger(__name__)
settings = get_settings()


def _task_or_none(db, task_id: str):
    try:
        parsed_id = UUID(task_id)
    except ValueError:
        return None

    return (
        db.query(TaskResult)
        .filter(TaskResult.id == parsed_id)
        .first()
    )


@celery_app.task(
    name="shared.export.tasks.generate_export",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_export_task(
    self,
    task_id: str,
    audit_id: int,
    user_id: int,
):
    try:
        with db_session() as db:
            task = _task_or_none(db, task_id)
            audit = (
                db.query(ExportAuditLog)
                .filter(ExportAuditLog.id == audit_id)
                .first()
            )

            if task is None or audit is None:
                raise ValueError("Export task record was not found")

            if task.status == "success":
                return task.result_json or {}

            task.status = "in_progress"
            task.error_message = None
            audit.status = "in_progress"
            audit.error_message = None

        with db_session() as db:
            task = _task_or_none(db, task_id)
            audit = (
                db.query(ExportAuditLog)
                .filter(ExportAuditLog.id == audit_id)
                .first()
            )
            user = (
                db.query(User)
                .filter(
                    User.id == user_id,
                    User.company_id == audit.company_id,
                )
                .first()
            )

            if task is None or audit is None or user is None:
                raise ValueError("Export task ownership could not be validated")

            dataset = get_dataset(audit.module, audit.entity)
            columns = resolve_columns(
                audit.module,
                audit.entity,
                list(audit.columns_json or []),
            )
            labels = column_labels(
                audit.module,
                audit.entity,
                columns,
            )
            filters = dict(audit.filters_json or {})
            rows = fetch_export_rows(
                db=db,
                current_user=user,
                module=audit.module,
                entity=audit.entity,
                filters=filters,
            )
            content, content_type, extension = render_export(
                export_format=audit.export_format,
                title=dataset.title,
                columns=columns,
                labels=labels,
                rows=rows,
                filters=filters,
            )

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = (
                f"{audit.module}_{audit.entity}_{timestamp}.{extension}"
            )

            manager = StorageManager(db)
            asset = manager.create_generated_asset(
                filename=filename,
                content_type=content_type,
                content=content,
                owner=user,
                purpose="phase1_export",
                commit=False,
            )
            download_url = manager.create_download_url(
                asset_id=asset.id,
                user=user,
            )

            result = {
                "asset_id": asset.id,
                "download_url": download_url,
                "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
                "filename": asset.original_filename,
                "format": audit.export_format,
                "row_count": len(rows),
            }

            task.status = "success"
            task.result_json = result
            task.error_message = None

            audit.status = "success"
            audit.file_asset_id = asset.id
            audit.row_count = len(rows)
            audit.error_message = None
            audit.completed_at = datetime.utcnow()

            return result

    except Exception as exc:
        retryable = isinstance(
            exc,
            (
                BotoCoreError,
                ClientError,
                DBAPIError,
                OperationalError,
            ),
        )
        should_retry = retryable and self.request.retries < self.max_retries

        logger.exception(
            "Export task failed task_id=%s audit_id=%s retry=%s",
            task_id,
            audit_id,
            should_retry,
        )

        with db_session() as db:
            task = _task_or_none(db, task_id)
            audit = (
                db.query(ExportAuditLog)
                .filter(ExportAuditLog.id == audit_id)
                .first()
            )

            if task is not None:
                task.status = "pending" if should_retry else "failure"
                task.error_message = str(exc)

            if audit is not None:
                audit.status = "pending" if should_retry else "failure"
                audit.error_message = str(exc)
                audit.completed_at = (
                    None if should_retry else datetime.utcnow()
                )

        if should_retry:
            raise self.retry(exc=exc)

        raise
