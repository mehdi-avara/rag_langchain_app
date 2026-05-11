from pathlib import Path
import shutil

from fastapi import Depends, APIRouter, status, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from Models import User
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
from settings import get_settings


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

    return ProfileImageOut(image_path=user.image_path)


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

