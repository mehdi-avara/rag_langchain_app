"""RBAC permissions for the currency shared module."""

PERMISSIONS = [
    # name, resource, action, description
    ("currencies:read",       "currencies",     "read",   "View currencies"),
    ("currencies:create",     "currencies",     "create", "Add a currency"),
    ("currencies:manage",     "currencies",     "manage", "Manage currencies (admin only)"),
    ("exchange_rates:read",   "exchange_rates", "read",   "View exchange rate history"),
    ("exchange_rates:create", "exchange_rates", "create", "Enter an exchange rate"),
]
