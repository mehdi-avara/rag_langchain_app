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
from settings import get_settings

settings = get_settings()

__all__ = ["get_db", "seed_default_user"]


def seed_default_user() -> None:
    """Create the default admin user if it doesn't already exist.

    Idempotent. Intended to be called once at application startup (see the
    startup hook in ``api.py``), never inside a request handler.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(User)
            .filter_by(username=settings.default_username)
            .first()
        )
        if not existing:
            db.add(
                User(
                    username=settings.default_username,
                    First_name=settings.default_firstname,
                    pw_hash=bcrypt.hash(settings.default_password),
                    role="admin",
                )
            )
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_default_user()
