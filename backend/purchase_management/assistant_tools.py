from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, SearchSpec, WriteSpec

from .models import PurchaseOrderStatus
from .search.service import search_purchase_order_hits

MODULE = "purchase_management"
API_PREFIX = "/purchase/orders"

P_READ = "purchase_management:orders:read"
P_SEARCH = "purchase_management:orders:search"
P_ASK = "purchase_management:orders:ask"
P_CREATE = "purchase_management:orders:create"
P_UPDATE = "purchase_management:orders:update"


class PurchaseAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_purchase_orders",
            description="Find purchase orders by reference number, title, supplier, status, or approval status.",
            permission=P_SEARCH,
            search_fn=search_purchase_order_hits,
            resource_type="purchase_order",
            id_attr="id",
            id_param="ids",
            title_fields=("reference_number", "title", "supplier_name", "status"),
            module=MODULE,
            citation_prefix="purchase_order",
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_purchase_order",
            description="Create a purchase order draft.",
            permission=P_CREATE,
            target_action="create_purchase_order",
            method="POST",
            endpoint=API_PREFIX,
            required=("currency_id", "base_currency_id"),
            fields=(
                PayloadField("title"),
                PayloadField("supplier_id", aliases=("supplier",), kind="int"),
                PayloadField("supplier_name"),
                PayloadField("currency_id", aliases=("currency",), kind="int"),
                PayloadField("base_currency_id", aliases=("base_currency",), kind="int"),
                PayloadField("exchange_rate_used", aliases=("exchange_rate",), kind="decimal", default="1"),
                PayloadField("description"),
            ),
        ),
        WriteSpec(
            intent="update_purchase_order",
            description="Update an existing purchase order draft.",
            permission=P_UPDATE,
            target_action="update_purchase_order",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("purchase_order_id", "po_id", "id"),
            fields=(
                PayloadField("title"),
                PayloadField("supplier_id", aliases=("supplier",), kind="int"),
                PayloadField("supplier_name"),
                PayloadField("currency_id", aliases=("currency",), kind="int"),
                PayloadField("base_currency_id", aliases=("base_currency",), kind="int"),
                PayloadField("exchange_rate_used", aliases=("exchange_rate",), kind="decimal"),
                PayloadField("description"),
                PayloadField("status", kind="enum", enum_values=tuple(item.value for item in PurchaseOrderStatus)),
            ),
        ),
    )


def register() -> PurchaseAssistantToolSet:
    toolset = PurchaseAssistantToolSet()
    register_toolset(toolset)
    return toolset


register()
