from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)


InvitationStatus = Literal[
    "pending",
    "accepted",
    "revoked",
    "expired",
]


def _normalize_email(
    value: str,
) -> str:
    value = value.strip().lower()

    if (
        "@" not in value
        or "." not in value.split("@")[-1]
    ):
        raise ValueError(
            "Invalid email"
        )

    return value


class AdminUserInvitationCreate(
    BaseModel
):
    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
    )

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    last_name: str | None = Field(
        default=None,
        max_length=100,
    )

    role_ids: list[int] = Field(
        default_factory=list,
    )

    @field_validator("email")
    @classmethod
    def validate_email(
        cls,
        value: str,
    ) -> str:
        return _normalize_email(
            value
        )

    @field_validator("first_name")
    @classmethod
    def normalize_first_name(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "first_name is required"
            )

        return value

    @field_validator("last_name")
    @classmethod
    def normalize_last_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return (
            value.strip()
            or None
        )

    @field_validator("role_ids")
    @classmethod
    def validate_role_ids(
        cls,
        value: list[int],
    ) -> list[int]:
        if any(
            role_id <= 0
            for role_id in value
        ):
            raise ValueError(
                "role_ids must be positive"
            )

        return sorted(
            set(value)
        )


class AdminUserInvitationOut(
    BaseModel
):
    id: int
    company_id: int
    email: str
    first_name: str
    last_name: str | None = None
    role_ids: list[int]
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    invited_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class AdminUserInvitationTokenOut(
    AdminUserInvitationOut
):
    invitation_token: str


class AdminUserInvitationActionOut(
    BaseModel
):
    success: bool = True
    changed: bool


class UserInvitationTokenIn(
    BaseModel
):
    invitation_token: SecretStr


class PublicUserInvitationStatusOut(
    BaseModel
):
    company_id: int
    company_name: str
    email: str
    first_name: str
    last_name: str | None = None
    status: InvitationStatus
    expires_at: datetime


class UserInvitationAcceptIn(
    BaseModel
):
    invitation_token: SecretStr
    password: SecretStr = Field(
        ...,
        min_length=8,
        max_length=128,
    )


class UserInvitationAcceptOut(
    BaseModel
):
    success: bool = True
    user_id: int
    company_id: int
    username: str
