from typing import Optional, List

from pydantic import BaseModel, Field

from schemas.users import RoleOut


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


class CurrentUserOut(BaseModel):
    id: int
    company_id: int
    username: str
    role: str
    First_name: str
    Last_name: Optional[str] = None
    image_path: Optional[str] = None
    roles: List[RoleOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


