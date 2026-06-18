from __future__ import annotations

import os
from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import FileAsset, FileAssetStatus, User
from schemas.asset import AssetUploadUrlOut, AssetCompleteUploadIn, AssetDownloadUrlOut
from settings import get_settings
from storage.manager import StorageManager

from ..models import FinancialReceiptFile
from ..schemas import FinancialReceiptFileOut, FinancialReceiptFileUploadUrlCreate
from ..services import get_receipt_or_404, receipt_file_to_out


settings = get_settings()
router = APIRouter(prefix="/receipts")


def _get_receipt_file_or_404(
    db: Session,
    receipt_id: int,
    file_id: int,
) -> FinancialReceiptFile:
    file_rec = (
        db.query(FinancialReceiptFile)
        .filter(
            FinancialReceiptFile.id == file_id,
            FinancialReceiptFile.receipt_id == receipt_id,
        )
        .first()
    )

    if not file_rec:
        raise HTTPException(status_code=404, detail="Receipt file not found")

    return file_rec


@router.get("/{receipt_id}/files", response_model=List[FinancialReceiptFileOut])
def list_receipt_files(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:read")),
):
    get_receipt_or_404(db, receipt_id, current_user)

    files = (
        db.query(FinancialReceiptFile)
        .filter(FinancialReceiptFile.receipt_id == receipt_id)
        .order_by(FinancialReceiptFile.id.desc())
        .all()
    )

    return [receipt_file_to_out(file_rec) for file_rec in files]


@router.post("/{receipt_id}/files/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_receipt_file_upload_url(
    receipt_id: int,
    payload: FinancialReceiptFileUploadUrlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:create")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)

    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose=f"financial_receipt:{receipt.id}",
        checksum=payload.checksum,
    )


@router.post("/{receipt_id}/files/complete-upload/{asset_id}", response_model=FinancialReceiptFileOut, status_code=status.HTTP_201_CREATED)
def complete_receipt_file_upload(
    receipt_id: int,
    asset_id: int,
    payload: AssetCompleteUploadIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:create")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)

    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    if asset.company_id != receipt.company_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.status != FileAssetStatus.READY.value:
        raise HTTPException(status_code=409, detail="Asset is not ready")

    existing = (
        db.query(FinancialReceiptFile)
        .filter(
            FinancialReceiptFile.receipt_id == receipt.id,
            FinancialReceiptFile.asset_id == asset.id,
        )
        .first()
    )

    if existing:
        return receipt_file_to_out(existing)

    record = FinancialReceiptFile(
        user_id=current_user.id,
        receipt_id=receipt.id,
        asset_id=asset.id,
        file_name=asset.original_filename,
        media_address=asset.storage_key,
        content_type=asset.content_type,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return receipt_file_to_out(record)


@router.post("/{receipt_id}/files", response_model=FinancialReceiptFileOut, status_code=status.HTTP_201_CREATED)
async def add_receipt_file(
    receipt_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:create")),
):
    receipt = get_receipt_or_404(db, receipt_id, current_user)

    original_name = Path(file.filename or "upload.bin").name
    extension = Path(original_name).suffix
    stored_name = f"{uuid4().hex}{extension}"

    base_dir = Path(settings.files_dir) / "companies" / str(current_user.company_id) / "financial_management" / "receipts" / str(receipt.id)
    base_dir.mkdir(parents=True, exist_ok=True)

    file_path = base_dir / stored_name
    file_bytes = await file.read()

    with file_path.open("wb") as buffer:
        buffer.write(file_bytes)

    record = FinancialReceiptFile(
        user_id=current_user.id,
        receipt_id=receipt.id,
        file_name=original_name,
        media_address=str(file_path),
        content_type=file.content_type,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return receipt_file_to_out(record)


@router.get("/{receipt_id}/files/{file_id}/download-url", response_model=AssetDownloadUrlOut)
def create_receipt_file_download_url(
    receipt_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:read")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

    asset_id = getattr(file_rec, "asset_id", None)
    if not asset_id:
        raise HTTPException(status_code=409, detail="This receipt file is stored locally and has no asset download URL")

    manager = StorageManager(db)
    download_url = manager.create_download_url(
        asset_id=asset_id,
        user=current_user,
        disposition="attachment",
    )

    return {
        "asset_id": asset_id,
        "download_url": download_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


@router.get("/{receipt_id}/files/{file_id}/preview-url", response_model=AssetDownloadUrlOut)
def create_receipt_file_preview_url(
    receipt_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:read")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

    asset_id = getattr(file_rec, "asset_id", None)
    if not asset_id:
        raise HTTPException(status_code=409, detail="This receipt file is stored locally and has no asset preview URL")

    manager = StorageManager(db)
    preview_url = manager.create_download_url(
        asset_id=asset_id,
        user=current_user,
        disposition="inline",
    )

    return {
        "asset_id": asset_id,
        "download_url": preview_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


@router.get("/{receipt_id}/files/{file_id}/download")
def download_receipt_file(
    receipt_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:read")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

    asset_id = getattr(file_rec, "asset_id", None)
    if asset_id:
        manager = StorageManager(db)
        download_url = manager.create_download_url(
            asset_id=asset_id,
            user=current_user,
            disposition="attachment",
        )
        return RedirectResponse(url=download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    file_path = Path(file_rec.media_address).resolve()
    allowed_base = (Path(settings.files_dir) / "companies" / str(current_user.company_id)).resolve()

    if not str(file_path).startswith(str(allowed_base)):
        raise HTTPException(status_code=403, detail="Invalid file path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Stored file is missing")

    return FileResponse(
        path=str(file_path),
        filename=file_rec.file_name,
        media_type=file_rec.content_type or "application/octet-stream",
    )


@router.delete("/{receipt_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt_file(
    receipt_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:receipt_files:delete")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

    asset_id = getattr(file_rec, "asset_id", None)
    if asset_id:
        manager = StorageManager(db)
        manager.delete_file(
            asset_id=asset_id,
            user=current_user,
            hard_delete=False,
        )
        db.delete(file_rec)
        db.commit()
        return None

    file_path = Path(file_rec.media_address).resolve()
    allowed_base = (Path(settings.files_dir) / "companies" / str(current_user.company_id)).resolve()

    if not str(file_path).startswith(str(allowed_base)):
        raise HTTPException(status_code=403, detail="Invalid file path")

    if file_path.is_file():
        os.remove(file_path)

    db.delete(file_rec)
    db.commit()

    return None
