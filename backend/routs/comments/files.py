import os
from typing import List

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

    if not os.path.isfile(file_rec.media_address):
        raise HTTPException(status_code=404, detail="Stored file is missing")

    return FileResponse(
        path=file_rec.media_address,
        filename=file_rec.file_name,
        media_type="application/octet-stream",
    )


@router.post(
    "/add/{comment_id}",
    response_model=CommentFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_file_to_comment(
    comment_id: int,
    upload: CommentFileUpload = Depends(_parse_file_upload),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("comments:files:manage")),
):
    _get_owned_comment(db, comment_id, current_user)

    base_dir = os.path.join(settings.files_dir, "comments", str(comment_id))
    os.makedirs(base_dir, exist_ok=True)

    file_path = os.path.join(base_dir, upload.file.filename)
    file_bytes = await upload.file.read()
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    new_file = CommentFile(
        user_id=current_user.id,
        comment_id=comment_id,
        file_name=upload.file.filename,
        media_address=file_path,
    )
    db.add(new_file)
    db.commit()
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

    if os.path.isfile(file_rec.media_address):
        os.remove(file_rec.media_address)

    db.delete(file_rec)
    db.commit()

    return None
