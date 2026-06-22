PERMISSIONS = [
    ("warehouse_management:locations:read", "warehouse_management.locations", "read", "View warehouses, zones, and storage locations"),
    ("warehouse_management:locations:manage", "warehouse_management.locations", "manage", "Manage warehouses, zones, and storage locations"),
    ("warehouse_management:stock:read", "warehouse_management.stock", "read", "View stock balances and low-stock items"),
    ("warehouse_management:stock:manage", "warehouse_management.stock", "manage", "Manage stock thresholds and stock counts"),
    ("warehouse_management:movements:read", "warehouse_management.movements", "read", "View stock movement history"),
    ("warehouse_management:movements:create", "warehouse_management.movements", "create", "Create manual stock movements and GRN backfills"),
    ("warehouse_management:search", "warehouse_management", "search", "Search warehouse stock"),
    ("warehouse_management:summary", "warehouse_management", "summary", "View warehouse inventory summaries"),
    ("warehouse_management:export", "warehouse_management", "export", "Export warehouse data"),
]
