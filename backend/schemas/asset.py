from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssetUploadUrlCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., gt=0)
    purpose: str = Field(..., min_length=1, max_length=80)
    checksum: str | None = None


class AssetUploadUrlOut(BaseModel):
    asset_id: int
    upload_url: str
    method: Literal["PUT"] = "PUT"
    expires_seconds: int
    headers: dict[str, str]


class AssetCompleteUploadIn(BaseModel):
    checksum: str | None = None
    # Opt-in: when True, a Document Intelligence job is chained after MinerU
    # finishes. Default False keeps the existing upload behavior unchanged.
    run_document_intelligence: bool = False


class AssetDownloadUrlOut(BaseModel):
    asset_id: int
    download_url: str
    expires_seconds: int


class FileAssetOut(BaseModel):
    id: int
    owner_id: int | None
    company_id: int
    original_filename: str
    content_type: str
    size_bytes: int
    checksum: str | None
    bucket: str
    storage_backend: str
    status: str
    purpose: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    class Config:
        from_attributes = True
