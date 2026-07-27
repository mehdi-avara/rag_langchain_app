"""RBAC permissions for financial_management."""

PERMISSIONS = [
    (
        "financial_management:purchase_cost_allocations:read",
        "financial_management.purchase_cost_allocations",
        "read",
        "View purchase-cost payment allocations",
    ),
    (
        "financial_management:purchase_cost_allocations:create",
        "financial_management.purchase_cost_allocations",
        "create",
        "Create purchase-cost payment allocations",
    ),
    (
        "financial_management:purchase_cost_allocations:delete",
        "financial_management.purchase_cost_allocations",
        "delete",
        "Delete purchase-cost payment allocations",
    ),
]
