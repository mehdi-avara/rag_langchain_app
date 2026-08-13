from datetime import datetime

from pydantic import BaseModel


class AdminSummaryUsersOut(BaseModel):
    total: int
    active: int
    inactive: int


class AdminSummaryRolesOut(BaseModel):
    total_custom: int
    active_custom: int
    inactive_custom: int


class AdminSummarySessionsOut(BaseModel):
    total: int
    active: int
    revoked: int
    expired: int
    stale: int


class AdminSummaryAuditOut(BaseModel):
    total: int
    last_24_hours: int
    latest_activity_at: datetime | None


class AdminSummaryCompanyOut(BaseModel):
    id: int
    name: str


class AdminSummaryOut(BaseModel):
    users: AdminSummaryUsersOut
    roles: AdminSummaryRolesOut
    sessions: AdminSummarySessionsOut
    audit: AdminSummaryAuditOut
    company: AdminSummaryCompanyOut
