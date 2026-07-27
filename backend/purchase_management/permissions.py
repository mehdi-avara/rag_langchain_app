"""RBAC permissions for purchase_management."""

PERMISSIONS = [
    ("purchase_management:orders:read", "purchase_management.orders", "read", "View purchase orders"),
    ("purchase_management:orders:create", "purchase_management.orders", "create", "Create purchase orders"),
    ("purchase_management:orders:update", "purchase_management.orders", "update", "Edit purchase orders"),
    ("purchase_management:orders:submit", "purchase_management.orders", "submit", "Submit purchase orders and amendments for approval"),
    ("purchase_management:orders:amend", "purchase_management.orders", "amend", "Open commercial amendments for approved purchase orders"),
    ("purchase_management:orders:delete", "purchase_management.orders", "delete", "Delete/cancel purchase orders"),
    ("purchase_management:orders:approve", "purchase_management.orders", "approve", "Approve or reject purchase orders"),
    ("purchase_management:orders:search", "purchase_management.orders", "search", "Search purchase orders"),
    ("purchase_management:orders:ask", "purchase_management.orders", "ask", "Ask AI about purchase orders"),
    ("purchase_management:phases:manage", "purchase_management.phases", "manage", "Update delivery phase schedules"),
    ("purchase_management:phases:split", "purchase_management.phases", "split", "Split unreceived delivery quantities"),
    ("purchase_management:costs:read", "purchase_management.costs", "read", "View purchase-order costs"),
    ("purchase_management:costs:manage", "purchase_management.costs", "manage", "Add and update purchase-order costs"),
    ("purchase_management:costs:confirm_actual", "purchase_management.costs", "confirm_actual", "Confirm actual purchase-order costs"),
    ("purchase_management:payment_summary:read", "purchase_management.payment_summary", "read", "View purchase-order payment summaries"),
    ("purchase_management:summary", "purchase_management", "summary", "View procurement totals"),
    ("purchase_management:export", "purchase_management", "export", "Export purchase orders"),
]
