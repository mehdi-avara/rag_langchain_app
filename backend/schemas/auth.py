from typing import Optional, List

from pydantic import BaseModel, Field, field_validator

from schemas.users import RoleOut


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=150)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("Invalid email")
        return value


class RegisterResponse(BaseModel):
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


class LogoutResponse(BaseModel):
    success: bool = True
    revoked_sessions: int = 1


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
