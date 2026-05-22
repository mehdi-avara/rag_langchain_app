import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from Models import User
from db.init_db import get_db
from deps import require_permission
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate, AssetUploadUrlOut
from settings import get_settings
from storage.manager import StorageManager

settings = get_settings()

router = APIRouter()

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


def _validate_audio_content_type(content_type: str | None) -> None:
    if content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type")


def _validate_audio_filename(filename: str | None) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio file extension")


def _validate_audio_size(size_bytes: int | None) -> None:
    max_size = getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 104857600)
    if size_bytes is not None and size_bytes > max_size:
        raise HTTPException(status_code=413, detail="Audio file is too large")


async def _send_audio_to_stt(filename: str, content_type: str, content: bytes) -> dict:
    async with httpx.AsyncClient(timeout=300) as client:
        files = {"file": (filename, content, content_type)}
        response = await client.post(f"{settings.STT_URL}/transcribe", files=files)
        response.raise_for_status()
        return response.json()


@router.post("/transcribe")
async def transcribe(
    current_user: User = Depends(require_permission("stt:use")),
    file: UploadFile = File(...),
):
    _validate_audio_content_type(file.content_type)
    _validate_audio_filename(file.filename)

    content = await file.read()
    _validate_audio_size(len(content))

    return await _send_audio_to_stt(
        filename=file.filename or "audio",
        content_type=file.content_type or "application/octet-stream",
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


@router.post("/transcribe/complete-upload/{asset_id}", status_code=status.HTTP_201_CREATED)
async def complete_audio_transcribe_upload(
    asset_id: int,
    payload: AssetCompleteUploadIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("stt:use")),
):
    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    _validate_audio_content_type(asset.content_type)
    _validate_audio_filename(asset.original_filename)
    _validate_audio_size(asset.size_bytes)

    suffix = Path(asset.original_filename or "").suffix.lower() or ".audio"
    with tempfile.TemporaryDirectory() as tmpdir:
        target_path = Path(tmpdir) / f"asset_{asset.id}{suffix}"
        manager.download_asset_to_path(
            asset_id=asset.id,
            user=current_user,
            target_path=target_path,
        )
        content = target_path.read_bytes()

    return await _send_audio_to_stt(
        filename=asset.original_filename or f"asset_{asset.id}{suffix}",
        content_type=asset.content_type,
        content=content,
    )
