from pydantic import BaseModel

class UserNotificationTokenOut(BaseModel):
    success: bool

class UserNotificationTokenIn(BaseModel):
    notification_token: str