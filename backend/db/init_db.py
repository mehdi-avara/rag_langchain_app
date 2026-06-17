"""Database session dependency and one-time data seeding.

Schema creation is owned exclusively by Alembic migrations. This module no
longer issues DDL (no ``Base.metadata.create_all``) and must never do so on a
per-request basis. ``get_db`` is re-exported from :mod:`db.session` so existing
imports (``from db.init_db import get_db``) keep working against the single,
canonical engine/sessionmaker.
"""
from passlib.hash import bcrypt

from db.session import SessionLocal, get_db  # re-exported for existing imports
from Models import User
from Models.rbac import Role
from settings import get_settings

settings = get_settings()

__all__ = ["get_db", "seed_default_user"]


def seed_default_user() -> None:
    """Ensure the default admin user exists and is linked to the admin role.

    Idempotent. Intended to be called once at application startup (see the
    startup hook in ``api.py``), after ``seed_rbac`` has created the system
    ``admin`` role. Schema is owned by Alembic migrations.

    The legacy ``users.role`` column alone grants nothing — authorization is
    driven by RBAC (``user.roles -> role.permissions``). So this also attaches
    the system-wide admin role (``company_id IS NULL``); without it the default
    user looks like an admin but has zero permissions.
    """
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter_by(username=settings.default_username)
            .first()
        )
        if user is None:
            user = User(
                username=settings.default_username,
                First_name=settings.default_firstname,
                pw_hash=bcrypt.hash(settings.default_password),
                role="admin",
            )
            db.add(user)
            db.flush()

        admin_role = (
            db.query(Role)
            .filter(Role.name == "admin", Role.company_id.is_(None))
            .first()
        )
        if admin_role is not None and admin_role not in user.roles:
            user.roles.append(admin_role)

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_default_user()
