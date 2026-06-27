"""RBAC helpers — the agent runs with exactly the caller's access, never more (PROMPT §5).

These wrap the same permission set ``require_permission`` consults
(``deps.get_user_permissions``), so the assistant's checks and the route guards
stay in lockstep. Read handlers call ``ensure_permission`` before invoking a
service; ``build_*_draft`` calls it early so an un-committable draft is never
offered; the router uses ``has_permission`` to filter the intent set.
"""

from __future__ import annotations

from Models import User
from deps import get_user_permissions

from .errors import permission_denied


def user_permissions(user: User) -> set[str]:
    return get_user_permissions(user)


def has_permission(user: User, permission: str) -> bool:
    return permission in get_user_permissions(user)


def ensure_permission(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise permission_denied(permission)
