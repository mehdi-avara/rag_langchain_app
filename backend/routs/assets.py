from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import User
from schemas.asset import (
    AssetCompleteUploadIn,
    AssetDownloadUrlOut,
    AssetUploadUrlCreate,
    AssetUploadUrlOut,
    FileAssetOut,
)
from settings import get_settings
from storage.manager import StorageManager

settings = get_settings()
router = APIRouter()


@router.post("/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_asset_upload_url(
    payload: AssetUploadUrlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose=payload.purpose,
        checksum=payload.checksum,
    )


@router.post("/{asset_id}/complete-upload", response_model=FileAssetOut)
def complete_asset_upload(
    asset_id: int,
    payload: AssetCompleteUploadIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager = StorageManager(db)
    return manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )


@router.get("/{asset_id}", response_model=FileAssetOut)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager = StorageManager(db)
    return manager.get_asset(asset_id=asset_id, user=current_user)


@router.get("/{asset_id}/download-url", response_model=AssetDownloadUrlOut)
def create_asset_download_url(
    asset_id: int,
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager = StorageManager(db)
    download_url = manager.create_download_url(
        asset_id=asset_id,
        user=current_user,
        disposition=disposition,
    )

    return {
        "asset_id": asset_id,
        "download_url": download_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager = StorageManager(db)
    manager.delete_file(asset_id=asset_id, user=current_user, hard_delete=hard_delete)
    return None
