from __future__ import annotations

from datetime import datetime
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models import FileAsset, FileAssetStatus, User
from settings import get_settings


settings = get_settings()


def _is_company_admin(user: User) -> bool:
    return user.role == "admin" or any(role.name == "admin" and role.is_active for role in user.roles)


def _clean_filename(filename: str) -> str:
    name = Path(filename or "upload.bin").name.strip()
    return name or "upload.bin"


class StorageManager:
    def __init__(self, db: Session):
        self.db = db
        self.bucket = settings.S3_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION_NAME,
            use_ssl=settings.S3_USE_SSL,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        public_endpoint = settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL
        self.presign_client = boto3.client(
            "s3",
            endpoint_url=public_endpoint,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION_NAME,
            use_ssl=settings.S3_USE_SSL,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def _allowed_content_types(self) -> set[str]:
        return {
            item.strip()
            for item in settings.ALLOWED_UPLOAD_CONTENT_TYPES.split(",")
            if item.strip()
        }

    def _validate_upload(self, content_type: str, size_bytes: int) -> None:
        if size_bytes <= 0:
            raise HTTPException(status_code=422, detail="Invalid file size")

        if size_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File is too large")

        allowed_types = self._allowed_content_types()
        if allowed_types and content_type not in allowed_types:
            raise HTTPException(status_code=415, detail="File content type is not allowed")

    def _get_asset_or_404(self, asset_id: int) -> FileAsset:
        asset = self.db.query(FileAsset).filter(FileAsset.id == asset_id).first()
        if not asset or asset.status == FileAssetStatus.DELETED.value or asset.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return asset

    def _check_company_access(self, asset: FileAsset, user: User) -> None:
        if user.company_id is None:
            raise HTTPException(status_code=403, detail="User has no company")

        if asset.company_id != user.company_id:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.owner_id == user.id:
            return

        if _is_company_admin(user):
            return

        raise HTTPException(status_code=403, detail="Permission denied")

    def create_upload_url(
        self,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        owner: User,
        purpose: str,
        checksum: str | None = None,
        expires_seconds: int | None = None,
    ) -> dict:
        if owner.company_id is None:
            raise HTTPException(status_code=403, detail="User has no company")

        self._validate_upload(content_type, size_bytes)
        self._ensure_bucket()

        original_filename = _clean_filename(filename)

        asset = FileAsset(
            owner_id=owner.id,
            company_id=owner.company_id,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
            bucket=self.bucket,
            storage_key="pending",
            storage_backend="s3",
            status=FileAssetStatus.PENDING.value,
            purpose=purpose,
        )

        self.db.add(asset)
        self.db.flush()

        asset.storage_key = f"companies/{owner.company_id}/assets/{asset.id}/original"
        self.db.commit()
        self.db.refresh(asset)

        expires = expires_seconds or settings.S3_UPLOAD_EXPIRES_SECONDS

        upload_url = self.presign_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": asset.bucket,
                "Key": asset.storage_key,
                "ContentType": asset.content_type,
            },
            ExpiresIn=expires,
        )

        return {
            "asset_id": asset.id,
            "upload_url": upload_url,
            "method": "PUT",
            "expires_seconds": expires,
            "headers": {"Content-Type": asset.content_type},
        }

    def complete_upload(self, *, asset_id: int, user: User, checksum: str | None = None) -> FileAsset:
        asset = self._get_asset_or_404(asset_id)
        self._check_company_access(asset, user)

        if asset.status != FileAssetStatus.PENDING.value:
            raise HTTPException(status_code=409, detail="Asset is not pending")

        try:
            metadata = self.client.head_object(Bucket=asset.bucket, Key=asset.storage_key)
        except ClientError as exc:
            asset.status = FileAssetStatus.FAILED.value
            asset.error_message = str(exc)
            self.db.commit()
            raise HTTPException(status_code=400, detail="Uploaded object was not found in storage") from exc

        actual_size = int(metadata.get("ContentLength") or 0)
        if actual_size != asset.size_bytes:
            asset.status = FileAssetStatus.FAILED.value
            asset.error_message = f"Size mismatch. expected={asset.size_bytes}, actual={actual_size}"
            self.db.commit()
            raise HTTPException(status_code=400, detail="Uploaded object size does not match metadata")

        if checksum:
            asset.checksum = checksum

        asset.status = FileAssetStatus.READY.value
        asset.error_message = None
        self.db.commit()
        self.db.refresh(asset)

        return asset

    def create_download_url(
        self,
        *,
        asset_id: int,
        user: User,
        expires_seconds: int | None = None,
        disposition: str = "attachment",
    ) -> str:
        asset = self._get_asset_or_404(asset_id)
        self._check_company_access(asset, user)

        if asset.status != FileAssetStatus.READY.value:
            raise HTTPException(status_code=409, detail="Asset is not ready")

        safe_filename = asset.original_filename.replace('"', "")
        expires = expires_seconds or settings.S3_DOWNLOAD_EXPIRES_SECONDS

        download_url = self.presign_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": asset.bucket,
                "Key": asset.storage_key,
                "ResponseContentType": asset.content_type,
                "ResponseContentDisposition": f'{disposition}; filename="{safe_filename}"',
            },
            ExpiresIn=expires,
        )

        return download_url

    def delete_file(self, *, asset_id: int, user: User, hard_delete: bool = False) -> None:
        asset = self._get_asset_or_404(asset_id)
        self._check_company_access(asset, user)

        if hard_delete:
            try:
                self.client.delete_object(Bucket=asset.bucket, Key=asset.storage_key)
            except ClientError:
                pass

        asset.status = FileAssetStatus.DELETED.value
        asset.deleted_at = datetime.utcnow()
        self.db.commit()

    def get_asset(self, *, asset_id: int, user: User) -> FileAsset:
        asset = self._get_asset_or_404(asset_id)
        self._check_company_access(asset, user)
        return asset
