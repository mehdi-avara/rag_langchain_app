from typing import Optional

from pydantic import BaseModel

class UserNotificationTokenOut(BaseModel):
    success: bool

class UserNotificationTokenIn(BaseModel):
    notification_token: str


class CurrentUserOut(BaseModel):
    id: int
    username: str
    role: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordOut(BaseModel):
    success: bool
