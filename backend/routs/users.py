from datetime import datetime
from pathlib import Path
import shutil

from fastapi import Depends, APIRouter, status, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from Models import User, FileAssetStatus
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


@router.put("", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
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
    db.commit()

    return ChangePasswordOut(success=True)


@router.post(
    "/profile-image",
    response_model=ProfileImageOut,
    status_code=status.HTTP_200_OK,
)
async def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("profile:image")),
    db: Session = Depends(get_db),
) -> ProfileImageOut:
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}

    if file.content_type not in allowed_types:
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

    images_dir = Path(settings.files_dir) / "profile_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    extension = Path(file.filename).suffix or ".jpg"
    new_filename = f"user_{user.id}{extension}"
    destination = images_dir / new_filename

    if user.image_path:
        previous = (Path(settings.files_dir) / user.image_path).resolve()

        try:
            if previous.exists():
                previous.unlink()
        except OSError:
            pass

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    user.image_path = str(Path("profile_images") / new_filename)

    db.commit()
    db.refresh(user)

    return ProfileImageOut(image_path=user.image_path, profile_asset_id=getattr(user, "profile_asset_id", None))


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

    file_path = (Path(settings.files_dir) / user.image_path).resolve()
    base_dir = Path(settings.files_dir).resolve()

    if not str(file_path).startswith(str(base_dir)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid image path")

    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile image not found")

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

