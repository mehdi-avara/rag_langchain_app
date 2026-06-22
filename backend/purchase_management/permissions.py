"""RBAC permissions for purchase_management."""

PERMISSIONS = [
    ("purchase_management:orders:read", "purchase_management.orders", "read", "View purchase orders"),
    ("purchase_management:orders:create", "purchase_management.orders", "create", "Create purchase orders"),
    ("purchase_management:orders:update", "purchase_management.orders", "update", "Edit purchase orders"),
    ("purchase_management:orders:delete", "purchase_management.orders", "delete", "Delete/cancel purchase orders"),
    ("purchase_management:orders:approve", "purchase_management.orders", "approve", "Approve or reject purchase orders"),
    ("purchase_management:orders:search", "purchase_management.orders", "search", "Search purchase orders"),
    ("purchase_management:orders:ask", "purchase_management.orders", "ask", "Ask AI about purchase orders"),
    ("purchase_management:phases:manage", "purchase_management.phases", "manage", "Create/update delivery phases"),
    ("purchase_management:costs:manage", "purchase_management.costs", "manage", "Add/update additional costs"),
    ("purchase_management:summary", "purchase_management", "summary", "View procurement totals"),
    ("purchase_management:export", "purchase_management", "export", "Export purchase orders"),
]
