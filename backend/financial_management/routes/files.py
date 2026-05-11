from __future__ import annotations

import os
from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User
from settings import get_settings

from ..models import FinancialReceiptFile
from ..schemas import FinancialReceiptFileOut
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
    current_user: User = Depends(require_permission("financial_management:files")),
):
    get_receipt_or_404(db, receipt_id, current_user)

    files = (
        db.query(FinancialReceiptFile)
        .filter(FinancialReceiptFile.receipt_id == receipt_id)
        .order_by(FinancialReceiptFile.id.desc())
        .all()
    )

    return [receipt_file_to_out(file_rec) for file_rec in files]


@router.post("/{receipt_id}/files", response_model=FinancialReceiptFileOut, status_code=status.HTTP_201_CREATED)
async def add_receipt_file(
    receipt_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:files")),
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


@router.get("/{receipt_id}/files/{file_id}/download")
def download_receipt_file(
    receipt_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("financial_management:files")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

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
    current_user: User = Depends(require_permission("financial_management:files")),
):
    get_receipt_or_404(db, receipt_id, current_user)
    file_rec = _get_receipt_file_or_404(db, receipt_id, file_id)

    file_path = Path(file_rec.media_address).resolve()
    allowed_base = (Path(settings.files_dir) / "companies" / str(current_user.company_id)).resolve()

    if not str(file_path).startswith(str(allowed_base)):
        raise HTTPException(status_code=403, detail="Invalid file path")

    if file_path.is_file():
        os.remove(file_path)

    db.delete(file_rec)
    db.commit()

    return None

