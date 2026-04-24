from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from db.session import SessionLocal
from Models.user import User
from Models.rbac import Role, Permission


def get_or_create_permission(
    db: Session,
    name: str,
    resource: str,
    action: str,
    description: str | None = None,
) -> Permission:
    permission = db.query(Permission).filter(Permission.name == name).first()

    if permission:
        permission.resource = resource
        permission.action = action
        permission.description = description
        return permission

    permission = Permission(
        name=name,
        resource=resource,
        action=action,
        description=description,
    )

    db.add(permission)
    db.flush()

    return permission


def get_or_create_role(
    db: Session,
    name: str,
    description: str | None = None,
) -> Role:
    role = db.query(Role).filter(Role.name == name).first()

    if role:
        role.description = description
        role.is_active = True
        return role

    role = Role(
        name=name,
        description=description,
        is_active=True,
    )

    db.add(role)
    db.flush()

    return role


def get_or_create_user(
    db: Session,
    username: str,
    password: str,
    first_name: str,
    last_name: str | None = None,
    legacy_role: str = "user",
) -> User:
    user = db.query(User).filter(User.username == username).first()

    if user:
        user.First_name = first_name
        user.Last_name = last_name
        user.role = legacy_role
        return user

    user = User(
        username=username,
        First_name=first_name,
        Last_name=last_name,
        pw_hash=bcrypt.hash(password),
        role=legacy_role,
    )

    db.add(user)
    db.flush()

    return user


def seed() -> None:
    db = SessionLocal()

    try:
        permissions_data = [
            ("users:read", "users", "read", "Read users"),
            ("users:create", "users", "create", "Create users"),
            ("users:update", "users", "update", "Update users"),
            ("users:delete", "users", "delete", "Delete users"),
            ("roles:read", "roles", "read", "Read roles"),
            ("roles:create", "roles", "create", "Create roles"),
            ("roles:update", "roles", "update", "Update roles"),
            ("roles:delete", "roles", "delete", "Delete roles"),
            ("permissions:read", "permissions", "read", "Read permissions"),
            ("permissions:create", "permissions", "create", "Create permissions"),
            ("permissions:update", "permissions", "update", "Update permissions"),
            ("permissions:delete", "permissions", "delete", "Delete permissions"),
            ("documents:read", "documents", "read", "Read documents"),
            ("documents:create", "documents", "create", "Create documents"),
            ("documents:update", "documents", "update", "Update documents"),
            ("documents:delete", "documents", "delete", "Delete documents"),
            ("documents:ask", "documents", "ask", "Ask documents"),
            ("documents:download", "documents", "download", "Download documents"),
            ("chat:use", "chat", "use", "Use chat"),
            ("chat:read", "chat", "read", "Read chat history"),
            ("chat:update", "chat", "update", "Update chat"),
            ("chat:delete", "chat", "delete", "Delete chat"),
            ("llm:read", "llm", "read", "Read LLM models"),
            ("llm:create", "llm", "create", "Create LLM models"),
            ("llm:update", "llm", "update", "Update LLM models"),
            ("llm:delete", "llm", "delete", "Delete LLM models"),
            ("stt:use", "stt", "use", "Use speech to text service"),
            ("profile:read", "profile", "read", "Read own profile"),
            ("profile:update", "profile", "update", "Update own profile"),
            ("profile:change_password", "profile", "change_password", "Change own password"),
            ("profile:image", "profile", "image", "Manage own profile image"),
            ("profile:notification", "profile", "notification", "Set own notification token"),
        ]

        permissions = [
            get_or_create_permission(db, name, resource, action, description)
            for name, resource, action, description in permissions_data
        ]

        permission_map = {permission.name: permission for permission in permissions}

        admin_role = get_or_create_role(db, "admin", "Administrator role")
        normal_role = get_or_create_role(db, "user", "Normal user role")

        admin_role.permissions = permissions

        normal_permission_names = {
            "users:read",
            "documents:read",
            "documents:create",
            "documents:delete",
            "documents:ask",
            "documents:download",
            "chat:use",
            "chat:read",
            "chat:update",
            "chat:delete",
            "llm:read",
            "profile:read",
            "profile:update",
            "profile:change_password",
            "profile:image",
            "profile:notification",
        }

        normal_role.permissions = [
            permission_map[name]
            for name in normal_permission_names
            if name in permission_map
        ]

        admin_user = get_or_create_user(
            db=db,
            username="admin",
            password="admin123",
            first_name="Admin",
            last_name="User",
            legacy_role="admin",
        )

        normal_user = get_or_create_user(
            db=db,
            username="user1",
            password="user123",
            first_name="Normal",
            last_name="User",
            legacy_role="user",
        )

        admin_user.roles = [admin_role]
        normal_user.roles = [normal_role]

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed()