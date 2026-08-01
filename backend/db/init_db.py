"""Database session dependency and one-time data seeding.

Schema creation is owned exclusively by Alembic migrations. This module no
longer issues DDL (no ``Base.metadata.create_all``) and must never do so on a
per-request basis. ``get_db`` is re-exported from :mod:`db.session` so existing
imports (``from db.init_db import get_db``) keep working against the single,
canonical engine/sessionmaker.
"""
from passlib.hash import bcrypt

from db.session import SessionLocal, get_db  # re-exported for existing imports
from db.provision_company_defaults import provision_company_defaults
from Models import Company, User
from Models.rbac import Role
from settings import get_settings

settings = get_settings()

__all__ = ["get_db", "seed_default_user"]



def _get_or_create_default_company(db) -> Company:
    """Return the default company, creating it if it does not exist yet.

    The default admin must belong to a company: ``CurrentUserOut.company_id``
    is a required int and most endpoints scope by ``users.company_id``, so a
    NULL leaves the seeded admin unable to load ``/user`` (500) or read
    ``/company/settings`` (403). Idempotent via the unique ``slug``.
    """
    company = (
        db.query(Company)
        .filter(Company.slug == settings.DEFAULT_COMPANY_SLUG)
        .first()
    )
    if company is None:
        company = Company(
            name=settings.DEFAULT_COMPANY_NAME,
            slug=settings.DEFAULT_COMPANY_SLUG,
            is_active=True,
        )
        db.add(company)
        db.flush()
    return company


def _validated_bootstrap_credentials() -> tuple[str, str, str]:
    username = settings.default_username.strip()
    password = settings.default_password
    first_name = settings.default_firstname.strip()

    if not username:
        raise RuntimeError(
            "Bootstrap admin username is required when bootstrap is enabled"
        )

    if not first_name:
        raise RuntimeError(
            "Bootstrap admin first name is required when bootstrap is enabled"
        )

    if len(password) < 16:
        raise RuntimeError(
            "Bootstrap admin password must contain at least 16 characters"
        )

    normalized_password = password.strip().lower()

    forbidden_passwords = {
        "admin",
        "admin123456",
        "password",
        "password123456",
        "changeme",
        "secret",
        "test",
        username.lower(),
    }

    if normalized_password in forbidden_passwords:
        raise RuntimeError(
            "Bootstrap admin password is insecure"
        )

    return username, password, first_name


def seed_default_user() -> None:
    if not settings.bootstrap_admin_enabled:
        return

    username, password, first_name = (
        _validated_bootstrap_credentials()
    )

    db = SessionLocal()

    try:
        existing_user = db.query(User.id).first()

        if existing_user is not None:
            raise RuntimeError(
                "Bootstrap admin can only run when the user table is empty"
            )

        company = _get_or_create_default_company(db)

        admin_role = (
            db.query(Role)
            .filter(
                Role.name == "admin",
                Role.company_id.is_(None),
                Role.is_system.is_(True),
                Role.is_active.is_(True),
            )
            .first()
        )

        if admin_role is None:
            raise RuntimeError(
                "Active global system admin role is required for bootstrap"
            )

        user = User(
            company_id=company.id,
            username=username,
            First_name=first_name,
            pw_hash=bcrypt.hash(password),
            role="admin",
        )

        user.roles.append(admin_role)

        db.add(user)
        db.flush()

        provision_company_defaults(
            db,
            company,
            created_by_user_id=user.id,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

if __name__ == "__main__":
    seed_default_user()
