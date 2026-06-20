from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from core.celery.celery_app import celery_app
from db.session import db_session
from Models import User
from Models.task_result import TaskResult
from storage.manager import StorageManager

from .services import upsert_item_from_import_row


def _normalized_header(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _task_or_none(db, task_id: str):
    try:
        parsed_id = UUID(task_id)
    except ValueError:
        return None

    return db.query(TaskResult).filter(TaskResult.id == parsed_id).first()


@celery_app.task(
    name="material_management.tasks.import_items",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def import_items_task(self, task_id: str, asset_id: int, user_id: int):
    try:
        from openpyxl import load_workbook

        with db_session() as db:
            task = _task_or_none(db, task_id)
            if task:
                task.status = "in_progress"
                task.error_message = None
                db.commit()

            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                raise ValueError(f"User {user_id} not found")

            manager = StorageManager(db)

            with tempfile.TemporaryDirectory() as temporary_directory:
                target_path = Path(temporary_directory) / f"material_import_{asset_id}.xlsx"
                manager.download_asset_to_path(
                    asset_id=asset_id,
                    user=user,
                    target_path=target_path,
                )

                workbook = load_workbook(filename=target_path, read_only=True, data_only=True)
                worksheet = workbook.active
                rows = worksheet.iter_rows(values_only=True)
                raw_headers = next(rows, None)

                if not raw_headers:
                    workbook.close()
                    raise ValueError("Import file has no header row")

                headers = [_normalized_header(value) for value in raw_headers]
                required_headers = {"item_code", "name", "category_code", "unit_code"}
                missing_headers = sorted(required_headers.difference(headers))

                if missing_headers:
                    workbook.close()
                    raise ValueError(
                        "Missing required columns: " + ", ".join(missing_headers)
                    )

                created = 0
                updated = 0
                skipped = 0
                errors = []

                for row_number, row_values in enumerate(rows, start=2):
                    row = {
                        headers[index]: row_values[index] if index < len(row_values) else None
                        for index in range(len(headers))
                    }

                    if not any(value not in (None, "") for value in row.values()):
                        skipped += 1
                        continue

                    try:
                        with db.begin_nested():
                            outcome = upsert_item_from_import_row(
                                db=db,
                                current_user=user,
                                row=row,
                            )

                        if outcome == "created":
                            created += 1
                        else:
                            updated += 1
                    except Exception as exc:
                        errors.append({"row": row_number, "message": str(exc)})

                workbook.close()

            result = {
                "asset_id": asset_id,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "error_count": len(errors),
                "errors": errors[:200],
            }

            if task:
                task.status = "success"
                task.result_json = result
                task.error_message = None

            db.commit()
            return result

    except Exception as exc:
        with db_session() as db:
            task = _task_or_none(db, task_id)
            if task:
                task.status = "failure"
                task.error_message = str(exc)
                db.commit()
        raise
