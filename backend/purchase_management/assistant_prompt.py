"""Purchase-owned assistant prompt metadata.

This module contains no executable purchase behavior. Validation, lookups, and
draft construction remain in the purchase services/toolset.
"""

MODULE_DISPLAY_TITLE = "Purchase Management"
MODULE_DESCRIPTION = (
    "Find and prepare drafts for purchase orders, including orders created directly "
    "or from an existing request for quotation (RFQ)."
)

MODULE_SPECIALIST_NOTES = (
    "A purchase order is a purchasing record; do not route material requisition, RFQ, supplier, or warehouse tasks here.",
    "Resolve referenced RFQs, suppliers, and currencies through their registered lookup resources; never invent their IDs.",
    "The assistant prepares purchase-order drafts only. The purchase endpoint performs the actual create or update after review.",
)

SEARCH_PURCHASE_ORDERS = {
    "slot_rules": (
        "Put free-text reference numbers, titles, supplier names, statuses, and approval text in query.",
        "Use ids only when the user literally gives numeric purchase-order IDs.",
    ),
    "examples": (
        "Find purchase order PO-2026-104.",
        "Show purchase orders for supplier ACME that are awaiting approval.",
    ),
    "specialist_notes": (
        "Search can match reference number, title, supplier, status, or approval status.",
    ),
}

ADD_PURCHASE_ORDER = {
    "slot_rules": (
        "Use rfq_query for an RFQ number/name and rfq_id only for a literal numeric RFQ ID.",
        "Use supplier_query or supplier_name for supplier text and supplier_id only for a literal numeric ID.",
        "Use currency_query/base_currency_query for currency codes or names; use *_id only for literal numeric IDs.",
        "For a direct order, extract currency, base currency, exchange rate when stated, title, supplier, and description.",
    ),
    "examples": (
        "Prepare a purchase order from RFQ RFQ-2026-18.",
        "Create a PO draft for ACME in USD with IRR as the base currency for replacement pump parts.",
    ),
    "specialist_notes": (
        "An order created from an RFQ needs a resolvable RFQ reference.",
        "A direct order requires resolvable transaction currency and base currency before it is committable.",
        "Supplier is required for every purchase order and must resolve to a valid supplier_id.",
    ),
}

UPDATE_PURCHASE_ORDER = {
    "slot_rules": (
        "Use purchase_order_id only when the user literally gives a numeric ID; otherwise retain reference text in purchase_order_query.",
        "Extract only fields the user asked to change.",
        "Supplier and currency references follow the same text-query versus literal-ID rule as create.",
    ),
    "examples": (
        "Update purchase order ID 42 and change its title to Emergency Pump Order.",
        "Change PO-2026-104's supplier to ACME (search by the PO reference and supplier name first).",
    ),
    "specialist_notes": (
        "The existing update draft builder currently requires a literal numeric purchase-order ID for its endpoint.",
        "Never reinterpret a purchase-order reference number as a database ID.",
    ),
}
