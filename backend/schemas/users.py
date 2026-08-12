from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator


class UserNotificationTokenOut(BaseModel):
    success: bool


class UserNotificationTokenIn(BaseModel):
    notification_token: str


class PermissionBase(BaseModel):
    name: str
    resource: str
    action: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    pass


class PermissionOut(PermissionBase):
    id: int

    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class RoleCreate(RoleBase):
    permission_ids: List[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permission_ids: Optional[List[int]] = None


class RoleOut(RoleBase):
    id: int
    company_id: Optional[int] = None
    is_system: bool = False
    permissions: List[PermissionOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CurrentUserOut(BaseModel):
    id: int
    company_id: int
    username: str
    role: str
    First_name: str
    Last_name: Optional[str] = None
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    roles: List[RoleOut] = Field(default_factory=list)

    class Config:
        from_attributes = True




class UserCreate(BaseModel):
    username: str
    password: str
    First_name: str
    Last_name: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    First_name: Optional[str] = None
    Last_name: Optional[str] = None
    notification_token: Optional[str] = None
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    role_ids: Optional[List[int]] = None


class UserUpdateIn(BaseModel):
    username: Optional[str] = None
    First_name: Optional[str] = None
    Last_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    First_name: str
    Last_name: Optional[str] = None
    role: str
    created_at: datetime
    notification_token: Optional[str] = None
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    roles: List[RoleOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ChangePasswordOut(BaseModel):
    success: bool


class ProfileImageOut(BaseModel):
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    download_url: Optional[str] = None


class AdminUserCreate(BaseModel):
    username: str
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str
    last_name: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_name_fields(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            if "first_name" not in data and "First_name" in data:
                data["first_name"] = data["First_name"]
            if "last_name" not in data and "Last_name" in data:
                data["last_name"] = data["Last_name"]
        return data


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    notification_token: Optional[str] = None
    role_ids: Optional[List[int]] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_name_fields(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            if "first_name" not in data and "First_name" in data:
                data["first_name"] = data["First_name"]
            if "last_name" not in data and "Last_name" in data:
                data["last_name"] = data["Last_name"]
        return data


class AdminUserPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class AdminUserListOut(BaseModel):
    id: int
    company_id: int
    username: str
    First_name: str
    Last_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    deactivated_at: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    notification_token: Optional[str] = None
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AdminUserOut(BaseModel):
    id: int
    company_id: int
    username: str
    First_name: str
    Last_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    deactivated_at: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    notification_token: Optional[str] = None
    image_path: Optional[str] = None
    profile_asset_id: Optional[int] = None
    roles: List[RoleOut] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AdminUserRolesUpdate(BaseModel):
    role_ids: List[int] = Field(default_factory=list)



class AdminAuthSessionOut(BaseModel):
    id: str
    user_id: int
    company_id: Optional[int] = None
    token_version: int
    created_at: datetime
    last_rotated_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None
    is_revoked: bool
    is_expired: bool


class AdminAuthSessionActionOut(BaseModel):
    success: bool
    revoked_sessions: int


class CurrentUserAccessOut(BaseModel):
    user_id: int
    company_id: Optional[int] = None
    username: str
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    is_admin: bool = False
    is_active: bool = True
