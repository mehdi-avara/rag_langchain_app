from fastapi import Depends, APIRouter, status, HTTPException
from sqlalchemy.orm import Session


from db.models import User
from db.init_db import get_db
from schemas.users import UserNotificationTokenOut,UserNotificationTokenIn
from deps import get_current_user


router = APIRouter()


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