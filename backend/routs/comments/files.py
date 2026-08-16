from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from db.init_db import get_db
from Models import Comment, User, CommentFile
from Models.file_asset import FileAssetStatus
from deps import get_current_user, require_permission
from schemas.asset import AssetUploadUrlCreate, AssetUploadUrlOut, AssetCompleteUploadIn, AssetDownloadUrlOut
from schemas.comment import CommentFileName, CommentFileOut, CommentFileUpload
from settings import get_settings
from storage.manager import StorageManager


settings = get_settings()

router = APIRouter(tags=["comments files"])

_LEGACY_COMMENT_FILE_CHUNK_SIZE = 1024 * 1024
_MAX_LEGACY_COMMENT_FILENAME_LENGTH = 255


def _allowed_comment_file_content_types() -> set[str]:
    return {
        item.strip()
        for item in settings.ALLOWED_UPLOAD_CONTENT_TYPES.split(",")
        if item.strip()
    }


def _legacy_comment_files_base(comment_id: int) -> Path:
    return (
        Path(settings.files_dir)
        / "comments"
        / str(comment_id)
    ).resolve()


def _resolve_legacy_comment_file_path(
    comment_id: int,
    media_address: str,
) -> Path:
    file_path = Path(media_address).resolve()
    allowed_base = _legacy_comment_files_base(comment_id)

    if not file_path.is_relative_to(allowed_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid comment file path",
        )

    return file_path


def _validate_legacy_comment_upload_metadata(
    file: UploadFile,
) -> tuple[str, str]:
    original_name = Path(
        file.filename or "comment-file"
    ).name.strip() or "comment-file"

    if len(original_name) > _MAX_LEGACY_COMMENT_FILENAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Filename is too long",
        )

    content_type = (file.content_type or "").strip()
    allowed_types = _allowed_comment_file_content_types()

    if not content_type or content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Comment file content type is not allowed",
        )

    return original_name, content_type


async def _store_legacy_comment_file(
    file: UploadFile,
    destination: Path,
) -> int:
    max_size = int(settings.MAX_UPLOAD_SIZE_BYTES)

    if max_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload size limit is misconfigured",
        )

    total_size = 0

    try:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        allowed_base = destination.parent.resolve()
        resolved_destination = destination.resolve()

        if not resolved_destination.is_relative_to(allowed_base):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid comment file path",
            )

        with resolved_destination.open("xb") as buffer:
            while True:
                chunk = await file.read(
                    _LEGACY_COMMENT_FILE_CHUNK_SIZE
                )

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Comment file is too large",
                    )

                buffer.write(chunk)

        if total_size <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid file size",
            )

    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store comment file",
        ) from exc

    return total_size


def _parse_file_upload(file: UploadFile = File(...), index: bool = False) -> CommentFileUpload:
    return CommentFileUpload(file=file, index=index)


def _get_owned_comment(db: Session, comment_id: int, current_user: User) -> Comment:
    comment = (
        db.query(Comment)
        .filter(Comment.id == comment_id, Comment.user_id == current_user.id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


def _get_comment_file_or_404(
    db: Session,
    comment_id: int,
    file_id: int,
    current_user: User,
) -> CommentFile:
    file_rec = (
        db.query(CommentFile)
        .filter(
            CommentFile.id == file_id,
            CommentFile.comment_id == comment_id,
            CommentFile.user_id == current_user.id,
        )
        .first()
    )

    if not file_rec:
        raise HTTPException(status_code=404, detail="File not found for this comment")

    return file_rec


@router.get("/{comment_id}", response_model=List[CommentFileName])
def list_comment_files(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)

    return (
        db.query(CommentFile)
        .filter(CommentFile.comment_id == comment_id, CommentFile.user_id == current_user.id)
        .order_by(CommentFile.id.desc())
        .all()
    )


@router.post("/{comment_id}/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_comment_file_upload_url(
    comment_id: int,
    payload: AssetUploadUrlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)

    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose=f"comment:{comment_id}",
        checksum=payload.checksum,
    )


@router.post("/{comment_id}/complete-upload/{asset_id}", response_model=CommentFileOut, status_code=status.HTTP_201_CREATED)
def complete_comment_file_upload(
    comment_id: int,
    asset_id: int,
    payload: AssetCompleteUploadIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)

    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    if asset.status != FileAssetStatus.READY.value:
        raise HTTPException(status_code=409, detail="Asset is not ready")

    existing = (
        db.query(CommentFile)
        .filter(
            CommentFile.comment_id == comment_id,
            CommentFile.user_id == current_user.id,
            CommentFile.asset_id == asset.id,
        )
        .first()
    )

    if existing:
        return existing

    new_file = CommentFile(
        user_id=current_user.id,
        comment_id=comment_id,
        asset_id=asset.id,
        file_name=asset.original_filename,
        media_address=asset.storage_key,
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return new_file


@router.get("/{comment_id}/{file_id}/download-url", response_model=AssetDownloadUrlOut)
def create_comment_file_download_url(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)
    file_rec = _get_comment_file_or_404(db, comment_id, file_id, current_user)

    asset_id = getattr(file_rec, "asset_id", None)
    if not asset_id:
        raise HTTPException(status_code=409, detail="This comment file is stored locally and has no asset download URL")

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


@router.get("/{comment_id}/{file_id}/preview-url", response_model=AssetDownloadUrlOut)
def create_comment_file_preview_url(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)
    file_rec = _get_comment_file_or_404(db, comment_id, file_id, current_user)

    asset_id = getattr(file_rec, "asset_id", None)
    if not asset_id:
        raise HTTPException(status_code=409, detail="This comment file is stored locally and has no asset preview URL")

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


@router.get("/{comment_id}/{file_id}/download")
def download_comment_file(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)
    file_rec = _get_comment_file_or_404(db, comment_id, file_id, current_user)

    asset_id = getattr(file_rec, "asset_id", None)
    if asset_id:
        manager = StorageManager(db)
        download_url = manager.create_download_url(
            asset_id=asset_id,
            user=current_user,
            disposition="attachment",
        )
        return RedirectResponse(download_url)

    file_path = _resolve_legacy_comment_file_path(
        comment_id,
        file_rec.media_address,
    )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Stored file is missing",
        )

    return FileResponse(
        path=file_path,
        filename=file_rec.file_name,
        media_type="application/octet-stream",
    )


@router.post(
    "/add/{comment_id}",
    response_model=CommentFileOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def add_file_to_comment(
    comment_id: int,
    upload: CommentFileUpload = Depends(_parse_file_upload),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)

    original_name, _content_type = (
        _validate_legacy_comment_upload_metadata(
            upload.file
        )
    )

    base_dir = _legacy_comment_files_base(comment_id)
    destination = (
        base_dir
        / f"{uuid4().hex}.upload"
    )

    await _store_legacy_comment_file(
        file=upload.file,
        destination=destination,
    )

    new_file = CommentFile(
        user_id=current_user.id,
        comment_id=comment_id,
        file_name=original_name,
        media_address=str(destination),
    )

    try:
        db.add(new_file)
        db.commit()
    except Exception:
        rollback = getattr(db, "rollback", None)

        if callable(rollback):
            rollback()

        destination.unlink(missing_ok=True)
        raise

    db.refresh(new_file)

    return new_file


@router.delete(
    "/{comment_id}/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_comment_file(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)
    file_rec = _get_comment_file_or_404(db, comment_id, file_id, current_user)

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

    file_path = _resolve_legacy_comment_file_path(
        comment_id,
        file_rec.media_address,
    )

    if file_path.is_file():
        file_path.unlink()

    db.delete(file_rec)
    db.commit()

    return None
