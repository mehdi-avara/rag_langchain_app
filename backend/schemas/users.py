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
    First_name: str
    Last_name: Optional[str] = None
    image_path: Optional[str] = None

    class Config:
        orm_mode = True


class UserUpdateIn(BaseModel):
    # username: Optional[str] = None
    First_name: Optional[str] = None
    Last_name: Optional[str] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordOut(BaseModel):
    success: bool


class ProfileImageOut(BaseModel):
    image_path: str
