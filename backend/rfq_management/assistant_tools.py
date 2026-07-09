from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    SearchSpec,
    WriteSpec,
    rfq_items_from_slots,
    rfq_required,
)

from .search.service import search_rfq_hits

MODULE = "rfq_management"
API_PREFIX = "/rfqs"

P_READ = "rfq_management:read"
P_SEARCH = "rfq_management:search"
P_ASK = "rfq_management:ask"
P_CREATE = "rfq_management:create"
P_UPDATE = "rfq_management:update"


class RFQAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_rfqs",
            description="Find RFQs by number, title, description, status, deadline, or requested items.",
            permission=P_SEARCH,
            search_fn=search_rfq_hits,
            resource_type="rfq",
            id_attr="rfq_id",
            id_param="rfq_ids",
            title_fields=("rfq_number", "title", "status"),
            module=MODULE,
            ask_intent="ask_rfqs",
            ask_description="Answer a grounded question using RFQ records as references.",
            ask_permission=P_ASK,
            citation_prefix="rfq",
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_rfq",
            description="Create an RFQ draft from a material requisition or explicit requested items.",
            permission=P_CREATE,
            target_action="create_rfq",
            method="POST",
            endpoint=API_PREFIX,
            required=("title", "deadline_date"),
            item_builder=rfq_items_from_slots,
            validate=rfq_required,
            fields=(
                PayloadField("mr_id", aliases=("requisition_id", "material_requisition_id"), kind="int"),
                PayloadField("title"),
                PayloadField("description"),
                PayloadField("deadline_date", aliases=("deadline", "date")),
                PayloadField("supplier_ids", aliases=("suppliers",), kind="raw", default=[]),
            ),
        ),
        WriteSpec(
            intent="update_rfq",
            description="Update an existing RFQ draft.",
            permission=P_UPDATE,
            target_action="update_rfq",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("rfq_id", "id"),
            fields=(
                PayloadField("title"),
                PayloadField("description"),
                PayloadField("deadline_date", aliases=("deadline", "date")),
            ),
        ),
    )


def register() -> RFQAssistantToolSet:
    toolset = RFQAssistantToolSet()
    register_toolset(toolset)
    return toolset


register()
