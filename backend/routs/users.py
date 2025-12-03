from fastapi import Depends, APIRouter, status, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil


from passlib.hash import bcrypt
from Models import User
from db.init_db import get_db
from schemas.users import (
    UserNotificationTokenOut,
    UserNotificationTokenIn,
    CurrentUserOut,
    ChangePasswordIn,
    ChangePasswordOut,
    UserUpdateIn,
    ProfileImageOut,
)
from deps import get_current_user
from settings import get_settings


router = APIRouter()
settings = get_settings()


@router.get("", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)) -> CurrentUserOut:
    """Return basic details for the authenticated user."""
    return CurrentUserOut(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        First_name=current_user.First_name,
        Last_name=current_user.Last_name,
        image_path=current_user.image_path,
    )


@router.put("", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
def update_user(
    payload: UserUpdateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurrentUserOut:
    """Update the current user's profile fields."""
    user = db.query(User).filter(User.id == current_user.id).first()
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
        username=user.username,
        role=user.role,
        First_name=user.First_name,
        Last_name=user.Last_name,
        image_path=user.image_path,
    )


@router.post("/change-pass", response_model=ChangePasswordOut, status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangePasswordOut:
    """Allow the authenticated user to update their password."""
    user = db.query(User).filter(User.id == current_user.id).first()
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileImageOut:
    """Upload or replace the current user's profile image."""
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: jpeg, png, gif, webp",
        )

    user = db.query(User).filter(User.id == current_user.id).first()
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
            # If deletion fails, continue to replace the file
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the current user's profile image."""
    user = db.query(User).filter(User.id == current_user.id).first()
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user.notification_token = payload.notification_token
        db.commit()
        db.refresh(user)
        return UserNotificationTokenOut(success=True)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
