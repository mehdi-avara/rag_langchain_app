import uuid
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from Models import User
from Models.task_result import TaskResult
from db.init_db import get_db
from deps import require_permission
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate, AssetUploadUrlOut
from settings import get_settings
from storage.manager import StorageManager

settings = get_settings()

router = APIRouter()


class TranscribeAsyncResponse(BaseModel):
    task_id: str
    status: str = "pending"
    message: str = "Audio queued for transcription. Poll GET /tasks/{task_id} for result."

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/webm",
    "audio/ogg",
}

ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".webm",
    ".ogg",
}

_AUDIO_UPLOAD_CHUNK_SIZE = 1024 * 1024
_AUDIO_SPOOL_MEMORY_LIMIT = 8 * 1024 * 1024


def _validate_audio_content_type(content_type: str | None) -> None:
    if content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type")


def _validate_audio_filename(filename: str | None) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio file extension")


def _audio_max_size() -> int:
    return int(
        getattr(
            settings,
            "MAX_UPLOAD_SIZE_BYTES",
            104857600,
        )
    )


def _validate_audio_size(size_bytes: int | None) -> None:
    max_size = _audio_max_size()
    if size_bytes is not None and size_bytes > max_size:
        raise HTTPException(
            status_code=413,
            detail="Audio file is too large",
        )


async def _copy_audio_bounded(
    file: UploadFile,
    target: BinaryIO,
) -> int:
    total_size = 0

    while True:
        chunk = await file.read(
            _AUDIO_UPLOAD_CHUNK_SIZE
        )

        if not chunk:
            break

        total_size += len(chunk)
        _validate_audio_size(total_size)
        target.write(chunk)

    return total_size


async def _send_audio_to_stt(
    filename: str,
    content_type: str,
    content: BinaryIO,
) -> dict:
    async with httpx.AsyncClient(timeout=300) as client:
        files = {
            "file": (
                filename,
                content,
                content_type,
            )
        }
        response = await client.post(
            f"{settings.STT_URL}/transcribe",
            files=files,
        )
        response.raise_for_status()
        return response.json()


@router.post("/transcribe")
async def transcribe(
    current_user: User = Depends(
        require_permission("stt:use")
    ),
    file: UploadFile = File(...),
):
    _validate_audio_content_type(
        file.content_type
    )
    _validate_audio_filename(
        file.filename
    )

    with SpooledTemporaryFile(
        max_size=_AUDIO_SPOOL_MEMORY_LIMIT,
        mode="w+b",
    ) as content:
        await _copy_audio_bounded(
            file,
            content,
        )
        content.seek(0)

        return await _send_audio_to_stt(
            filename=file.filename or "audio",
            content_type=(
                file.content_type
                or "application/octet-stream"
            ),
            content=content,
        )


@router.post("/transcribe/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_audio_transcribe_upload_url(
    payload: AssetUploadUrlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("stt:use")),
):
    _validate_audio_content_type(payload.content_type)
    _validate_audio_filename(payload.filename)
    _validate_audio_size(payload.size_bytes)

    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose="stt_audio",
        checksum=payload.checksum,
    )


@router.post(
    "/transcribe/complete-upload/{asset_id}",
    response_model=TranscribeAsyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def complete_audio_transcribe_upload(
    asset_id: int,
    payload: AssetCompleteUploadIn,
    language: Optional[str] = Query(None, description="ISO-639 language code hint, e.g. 'fa', 'en'"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("stt:use")),
):
    """Accept a pre-uploaded audio asset and queue it for async STT.

    Returns 202 immediately with a task_id.
    Frontend polls  GET /tasks/{task_id}  for completion.
    """
    from core.celery.celery_app import celery_app

    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    _validate_audio_content_type(asset.content_type)
    _validate_audio_filename(asset.original_filename)
    _validate_audio_size(asset.size_bytes)

    # Create a TaskResult row before dispatching so the task_id is stable
    task_record = TaskResult(
        id=uuid.uuid4(),
        task_type="stt_transcription",
        status="pending",
        created_by_user_id=current_user.id,
    )
    db.add(task_record)
    db.flush()  # assigns id without committing

    # Dispatch Celery task; capture celery_task_id on the record
    celery_result = celery_app.send_task(
        "stt.transcribe_audio",
        args=[asset.id, current_user.id, language],
    )
    task_record.celery_task_id = celery_result.id
    db.commit()

    return TranscribeAsyncResponse(task_id=str(task_record.id))
