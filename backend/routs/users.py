from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, APIRouter, status, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from Models import User, FileAssetStatus
from core.auth_sessions import revoke_user_authentication
from db.init_db import get_db
from deps import require_permission
from schemas.users import (
    UserNotificationTokenOut,
    UserNotificationTokenIn,
    CurrentUserOut,
    ChangePasswordIn,
    ChangePasswordOut,
    UserUpdateIn,
    ProfileImageOut,
)
from schemas.asset import AssetUploadUrlCreate, AssetUploadUrlOut, AssetCompleteUploadIn, AssetDownloadUrlOut
from settings import get_settings
from storage.manager import StorageManager


router = APIRouter()
settings = get_settings()

_LEGACY_PROFILE_IMAGE_CHUNK_SIZE = 1024 * 1024
_MAX_LEGACY_PROFILE_FILENAME_LENGTH = 255
_PROFILE_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
_PROFILE_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _allowed_profile_image_content_types() -> set[str]:
    central_types = {
        item.strip()
        for item in settings.ALLOWED_UPLOAD_CONTENT_TYPES.split(",")
        if item.strip()
    }

    if not central_types:
        return set(_PROFILE_IMAGE_CONTENT_TYPES)

    return _PROFILE_IMAGE_CONTENT_TYPES & central_types


def _validate_legacy_profile_image_metadata(
    file: UploadFile,
) -> tuple[str, str]:
    original_name = Path(
        file.filename or "profile-image"
    ).name.strip() or "profile-image"

    if len(original_name) > _MAX_LEGACY_PROFILE_FILENAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Filename is too long",
        )

    content_type = (file.content_type or "").strip()
    allowed_types = _allowed_profile_image_content_types()

    if not content_type or content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Profile image content type is not allowed",
        )

    return content_type, _PROFILE_IMAGE_EXTENSIONS[content_type]


async def _store_legacy_profile_image(
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

        with destination.open("xb") as buffer:
            while True:
                chunk = await file.read(
                    _LEGACY_PROFILE_IMAGE_CHUNK_SIZE
                )

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Profile image is too large",
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
            detail="Failed to store profile image",
        ) from exc

    return total_size


def _legacy_profile_images_base() -> Path:
    return (
        Path(settings.files_dir)
        / "profile_images"
    ).resolve()


def _resolve_legacy_profile_image_path(
    image_path: str,
) -> Path:
    file_path = (
        Path(settings.files_dir)
        / image_path
    ).resolve()

    allowed_base = _legacy_profile_images_base()

    if not file_path.is_relative_to(allowed_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid image path",
        )

    return file_path


def get_user_permission_names(user: User) -> list[str]:
    return sorted(
        {
            permission.name
            for role in user.roles
            if role.is_active
            for permission in role.permissions
        }
    )


@router.get("", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
def get_me(
    current_user: User = Depends(require_permission("profile:read")),
) -> CurrentUserOut:
    return CurrentUserOut(
        id=current_user.id,
        company_id=current_user.company_id,
        username=current_user.username,
        role=current_user.role,
        First_name=current_user.First_name,
        Last_name=current_user.Last_name,
        image_path=current_user.image_path,
        profile_asset_id=current_user.profile_asset_id,
        roles=current_user.roles,
        permissions=get_user_permission_names(current_user),
    )


@router.patch("", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
def update_user(
    payload: UserUpdateIn,
    current_user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
) -> CurrentUserOut:
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.username and payload.username != user.username:
        existing_user = db.query(User).filter(User.username == payload.username).first()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already in use",
            )

        user.username = payload.username

    if payload.First_name is not None:
        user.First_name = payload.First_name

    if payload.Last_name is not None:
        user.Last_name = payload.Last_name

    db.commit()
    db.refresh(user)

    return CurrentUserOut(
        id=user.id,
        company_id=user.company_id,
        username=user.username,
        role=user.role,
        First_name=user.First_name,
        Last_name=user.Last_name,
        image_path=user.image_path,
        profile_asset_id=user.profile_asset_id,
        roles=user.roles,
        permissions=get_user_permission_names(user),
    )


@router.post("/change-pass", response_model=ChangePasswordOut, status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordIn,
    current_user: User = Depends(require_permission("profile:change_password")),
    db: Session = Depends(get_db),
) -> ChangePasswordOut:
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not bcrypt.verify(payload.current_password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.pw_hash = bcrypt.hash(payload.new_password)
    user.password_changed_at = datetime.utcnow()

    revoke_user_authentication(
        db,
        user,
        reason="password_changed",
    )

    db.commit()

    return ChangePasswordOut(success=True)


@router.post(
    "/profile-image",
    response_model=ProfileImageOut,
    status_code=status.HTTP_200_OK,
    deprecated=True,
)
async def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
) -> ProfileImageOut:
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    content_type, extension = (
        _validate_legacy_profile_image_metadata(file)
    )

    images_dir = _legacy_profile_images_base()
    new_filename = (
        f"user_{user.id}_{uuid4().hex}{extension}"
    )
    destination = images_dir / new_filename

    previous_local_path = None

    if user.image_path and not user.profile_asset_id:
        try:
            previous_local_path = (
                _resolve_legacy_profile_image_path(
                    user.image_path
                )
            )
        except HTTPException:
            previous_local_path = None

    await _store_legacy_profile_image(
        file=file,
        destination=destination,
    )

    old_image_path = user.image_path
    old_profile_asset_id = user.profile_asset_id

    user.image_path = str(
        Path("profile_images") / new_filename
    )
    user.profile_asset_id = None

    try:
        db.commit()
    except Exception:
        rollback = getattr(db, "rollback", None)

        if callable(rollback):
            rollback()

        user.image_path = old_image_path
        user.profile_asset_id = old_profile_asset_id
        destination.unlink(missing_ok=True)
        raise

    db.refresh(user)

    if (
        previous_local_path is not None
        and previous_local_path != destination
    ):
        try:
            previous_local_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass

    return ProfileImageOut(
        image_path=user.image_path,
        profile_asset_id=user.profile_asset_id,
    )


@router.post(
    "/profile-image/upload-url",
    response_model=AssetUploadUrlOut,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_image_upload_url(
    payload: AssetUploadUrlCreate,
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
):
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}

    if payload.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: jpeg, png, gif, webp",
        )

    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose=f"profile_image:{user.id}",
        checksum=payload.checksum,
    )


@router.post(
    "/profile-image/complete-upload/{asset_id}",
    response_model=ProfileImageOut,
    status_code=status.HTTP_200_OK,
)
def complete_profile_image_upload(
    asset_id: int,
    payload: AssetCompleteUploadIn,
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}

    if asset.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: jpeg, png, gif, webp",
        )

    if asset.status != FileAssetStatus.READY.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset is not ready")

    user.profile_asset_id = asset.id
    user.image_path = asset.storage_key

    db.commit()
    db.refresh(user)

    download_url = manager.create_download_url(
        asset_id=asset.id,
        user=current_user,
        disposition="inline",
    )

    return ProfileImageOut(
        image_path=user.image_path,
        profile_asset_id=user.profile_asset_id,
        download_url=download_url,
    )


@router.get(
    "/profile-image/download-url",
    response_model=AssetDownloadUrlOut,
    status_code=status.HTTP_200_OK,
)
def create_profile_image_download_url(
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.profile_asset_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile image asset set")

    manager = StorageManager(db)
    download_url = manager.create_download_url(
        asset_id=user.profile_asset_id,
        user=current_user,
        disposition="inline",
    )

    return {
        "asset_id": user.profile_asset_id,
        "download_url": download_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


@router.get(
    "/profile-image/preview-url",
    response_model=AssetDownloadUrlOut,
    status_code=status.HTTP_200_OK,
)
def create_profile_image_preview_url(
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.profile_asset_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile image asset set")

    manager = StorageManager(db)
    preview_url = manager.create_download_url(
        asset_id=user.profile_asset_id,
        user=current_user,
        disposition="inline",
    )

    return {
        "asset_id": user.profile_asset_id,
        "download_url": preview_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


@router.get(
    "/profile-image",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
)
def download_profile_image(
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.profile_asset_id:
        manager = StorageManager(db)
        download_url = manager.create_download_url(
            asset_id=user.profile_asset_id,
            user=current_user,
            disposition="inline",
        )
        return RedirectResponse(download_url)

    if not user.image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile image set")

    file_path = _resolve_legacy_profile_image_path(
        user.image_path
    )

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile image not found",
        )

    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    media_type = media_types.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_path.name,
    )


@router.post("/set-notification-token", response_model=UserNotificationTokenOut, status_code=status.HTTP_200_OK)
def set_notification_token(
    payload: UserNotificationTokenIn,
    current_user: User = Depends(require_permission("profile:notification")),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == current_user.id,
        User.company_id == current_user.company_id,
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.notification_token = payload.notification_token

    db.commit()
    db.refresh(user)

    return UserNotificationTokenOut(success=True)
