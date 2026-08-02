from sqlalchemy.orm import Session

from db.session import SessionLocal
from Models.rbac import Role, Permission
from purchase_management.permissions import PERMISSIONS as PURCHASE_MANAGEMENT_PERMISSIONS
from financial_management.permissions import PERMISSIONS as FINANCIAL_MANAGEMENT_PERMISSIONS
from shared.currency.permissions import PERMISSIONS as CURRENCY_PERMISSIONS
from material_management.permissions import PERMISSIONS as MATERIAL_MANAGEMENT_PERMISSIONS
from requisition_management.permissions import PERMISSIONS as REQUISITION_MANAGEMENT_PERMISSIONS
from rfq_management.permissions import PERMISSIONS as RFQ_MANAGEMENT_PERMISSIONS
from goods_receipt_management.permissions import PERMISSIONS as GOODS_RECEIPT_MANAGEMENT_PERMISSIONS
from warehouse_management.permissions import PERMISSIONS as WAREHOUSE_MANAGEMENT_PERMISSIONS
from supplier_management.permissions import PERMISSIONS as SUPPLIER_MANAGEMENT_PERMISSIONS
from business_management.permissions import PERMISSIONS as BUSINESS_MANAGEMENT_PERMISSIONS
from assistant.permissions import PERMISSIONS as ASSISTANT_PERMISSIONS
from organization_management.permissions import PERMISSIONS as ORGANIZATION_MANAGEMENT_PERMISSIONS
from workflow_management.permissions import PERMISSIONS as WORKFLOW_MANAGEMENT_PERMISSIONS


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
        role.is_system = True
        role.company_id = None
        return role

    role = Role(
        name=name,
        description=description,
        is_active=True,
        is_system=True,
        company_id=None,
    )

    db.add(role)
    db.flush()

    return role



def seed() -> None:
    db = SessionLocal()

    try:
        permissions_data = [
            ("users:read", "users", "read", "Read users"),
            ("users:create", "users", "create", "Create users"),
            ("users:update", "users", "update", "Update users"),
            ("users:roles:manage", "users.roles", "manage", "Manage user roles"),
            ("users:status:manage", "users.status", "manage", "Activate and deactivate users"),
            ("users:password:reset", "users.password", "reset", "Reset user passwords"),
            ("roles:read", "roles", "read", "Read roles"),
            ("roles:create", "roles", "create", "Create roles"),
            ("roles:update", "roles", "update", "Update roles"),
            ("roles:delete", "roles", "delete", "Delete roles"),
            ("permissions:read", "permissions", "read", "Read permissions"),
            ("company:read", "company", "read", "Read company settings"),
            ("company:update", "company", "update", "Update company settings"),
            (
                "developer_docs:read",
                "developer_docs",
                "read",
                "Read backend developer documentation",
            ),
            ("documents:read", "documents", "read", "Read documents"),
            ("documents:create", "documents", "create", "Create documents"),
            ("documents:update", "documents", "update", "Update documents"),
            ("documents:delete", "documents", "delete", "Delete documents"),
            ("documents:search", "documents", "search", "Search documents"),
            ("documents:ask", "documents", "ask", "Ask documents"),
            ("documents:download", "documents", "download", "Download documents"),
            ("documents:versions:manage", "documents.versions", "manage", "Manage document versions"),
            ("documents:access:manage", "documents.access", "manage", "Manage document access"),
            ("comments:create", "comments", "create", "Create comments"),
            ("comments:read", "comments", "read", "Read comments"),
            ("comments:update", "comments", "update", "Update comments"),
            ("comments:delete", "comments", "delete", "Delete comments"),
            ("comments:search", "comments", "search", "Search comments"),
            ("comments:ask", "comments", "ask", "Ask comments"),
            ("comments:files:manage", "comments.files", "manage", "Manage comment files"),
            ("models:read", "models", "read", "Read models"),
            ("models:create", "models", "create", "Create models"),
            ("models:update", "models", "update", "Update models"),
            ("models:delete", "models", "delete", "Delete models"),
            ("models:search", "models", "search", "Search models"),
            ("models:ask", "models", "ask", "Ask models"),
            ("models:documents:manage", "models.documents", "manage", "Manage model documents"),
            ("models:comments:manage", "models.comments", "manage", "Manage model comments"),
            ("models:receipts:manage", "models.receipts", "manage", "Manage model receipts"),
            ("tags:read", "tags", "read", "Read tags"),
            ("tags:create", "tags", "create", "Create tags"),
            ("tags:update", "tags", "update", "Update tags"),
            ("tags:delete", "tags", "delete", "Delete tags"),
            ("tags:search", "tags", "search", "Search tags"),
            ("tags:ask", "tags", "ask", "Ask tags"),
            ("tags:documents:manage", "tags.documents", "manage", "Manage tag documents"),
            ("tags:comments:manage", "tags.comments", "manage", "Manage tag comments"),
            ("tags:models:manage", "tags.models", "manage", "Manage tag models"),
            ("tags:receipts:manage", "tags.receipts", "manage", "Manage tag receipts"),
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
            ("financial_management:read", "financial_management", "read", "Legacy: read financial data"),
            ("financial_management:cards:create", "financial_management.cards", "create", "Create financial cards"),
            ("financial_management:cards:read", "financial_management.cards", "read", "Read financial cards"),
            ("financial_management:cards:update", "financial_management.cards", "update", "Update financial cards"),
            ("financial_management:cards:delete", "financial_management.cards", "delete", "Delete financial cards"),
            ("financial_management:customers:create", "financial_management.customers", "create", "Create financial customers"),
            ("financial_management:customers:read", "financial_management.customers", "read", "Read financial customers"),
            ("financial_management:customers:update", "financial_management.customers", "update", "Update financial customers"),
            ("financial_management:customers:delete", "financial_management.customers", "delete", "Delete financial customers"),
            ("financial_management:receipts:create", "financial_management.receipts", "create", "Create financial receipts"),
            ("financial_management:receipts:read", "financial_management.receipts", "read", "Read financial receipts"),
            ("financial_management:receipts:update", "financial_management.receipts", "update", "Update financial receipts"),
            ("financial_management:receipts:delete", "financial_management.receipts", "delete", "Delete financial receipts"),
            ("financial_management:receipts:search", "financial_management.receipts", "search", "Search financial receipts"),
            ("financial_management:receipts:ask", "financial_management.receipts", "ask", "Ask financial receipts"),
            ("financial_management:receipt_files:create", "financial_management.receipt_files", "create", "Create financial receipt files"),
            ("financial_management:receipt_files:read", "financial_management.receipt_files", "read", "Read financial receipt files"),
            ("financial_management:receipt_files:delete", "financial_management.receipt_files", "delete", "Delete financial receipt files"),
            ("financial_management:receipt_comments:create", "financial_management.receipt_comments", "create", "Create financial receipt comment links"),
            ("financial_management:receipt_comments:read", "financial_management.receipt_comments", "read", "Read financial receipt comments"),
            ("financial_management:receipt_comments:delete", "financial_management.receipt_comments", "delete", "Delete financial receipt comment links"),
            ("financial_management:receipt_comments:search", "financial_management.receipt_comments", "search", "Search financial receipt comments"),
            ("property_management:read", "property_management", "read", "Read warehouse and property data"),
            ("property_management:create", "property_management", "create", "Create warehouse and property data"),
            ("property_management:update", "property_management", "update", "Update warehouse and property data"),
            ("property_management:delete", "property_management", "delete", "Delete warehouse and property data"),
            ("property_management:summary", "property_management", "summary", "Read net worth summary"),
        ]

        permissions_data.extend(PURCHASE_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(FINANCIAL_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(CURRENCY_PERMISSIONS)
        permissions_data.extend(SUPPLIER_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(MATERIAL_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(REQUISITION_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(RFQ_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(GOODS_RECEIPT_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(WAREHOUSE_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(BUSINESS_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(ASSISTANT_PERMISSIONS)
        permissions_data.extend(ORGANIZATION_MANAGEMENT_PERMISSIONS)
        permissions_data.extend(WORKFLOW_MANAGEMENT_PERMISSIONS)

        permissions = [
            get_or_create_permission(db, name, resource, action, description)
            for name, resource, action, description in permissions_data
        ]

        permission_map = {permission.name: permission for permission in permissions}

        admin_role = get_or_create_role(db, "admin", "Administrator role")

        # Track whether the built-in "user" role already exists, so we only seed
        # its default permissions on first creation. After that, role↔permission
        # assignments are managed by an admin at runtime (RBAC API) and must not
        # be overwritten on every startup.
        normal_role_existed = (
            db.query(Role).filter(Role.name == "user").first() is not None
        )
        normal_role = get_or_create_role(db, "user", "Normal user role")

        # The admin role always holds the full permission set — bootstrap so an
        # administrator can never be locked out and can manage every other role.
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
            "financial_management:read",
            "financial_management:cards:create",
            "financial_management:cards:read",
            "financial_management:cards:update",
            "financial_management:cards:delete",
            "financial_management:customers:create",
            "financial_management:customers:read",
            "financial_management:customers:update",
            "financial_management:customers:delete",
            "financial_management:receipts:create",
            "financial_management:receipts:read",
            "financial_management:receipts:update",
            "financial_management:receipts:delete",
            "financial_management:receipts:search",
            "financial_management:receipts:ask",
            "financial_management:receipt_files:create",
            "financial_management:receipt_files:read",
            "financial_management:receipt_files:delete",
            "financial_management:receipt_comments:create",
            "financial_management:receipt_comments:read",
            "financial_management:receipt_comments:delete",
            "financial_management:receipt_comments:search",
            "assistant:chat",
            "assistant:draft",
            "assistant:files",
            "models:documents:manage",
            "models:comments:manage",
            "models:receipts:manage",
            "tags:documents:manage",
            "tags:comments:manage",
            "tags:models:manage",
            "tags:receipts:manage",
            "property_management:read",
            "property_management:create",
            "property_management:update",
            "property_management:delete",
            "property_management:summary",
            # purchase_management permissions are intentionally NOT defaulted to
            # the normal role — grant them per-role via the admin RBAC API.
        }

        # Seed the normal role's default permissions only when it is first
        # created; leave admin-managed assignments untouched on later runs.
        if not normal_role_existed:
            normal_role.permissions = [
                permission_map[name]
                for name in normal_permission_names
                if name in permission_map
            ]

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed()
