from fastapi import Depends, APIRouter, status, HTTPException
from sqlalchemy.orm import Session


from passlib.hash import bcrypt
from Models import User
from db.init_db import get_db
from schemas.users import (
    UserNotificationTokenOut,
    UserNotificationTokenIn,
    CurrentUserOut,
    ChangePasswordIn,
    ChangePasswordOut,
)
from deps import get_current_user


router = APIRouter()


@router.get("/", response_model=CurrentUserOut, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)) -> CurrentUserOut:
    """Return basic details for the authenticated user."""
    return CurrentUserOut(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
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
