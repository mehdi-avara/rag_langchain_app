from __future__ import annotations

from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    SearchSpec,
    WriteSpec,
    requisition_items_from_slots,
)

from .models import MaterialRequisitionPriority
from .search.service import search_requisition_hits

MODULE = "requisition_management"
API_PREFIX = "/requisitions"

P_READ = "requisition_management:read"
P_SEARCH = "requisition_management:search"
P_ASK = "requisition_management:ask"
P_CREATE = "requisition_management:create"
P_UPDATE = "requisition_management:update"


class RequisitionAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_requisitions",
            description="Find material requisitions by MR number, status, priority, item, needed date, or reason.",
            permission=P_SEARCH,
            search_fn=search_requisition_hits,
            resource_type="requisition",
            id_attr="requisition_id",
            id_param="requisition_ids",
            title_fields=("mr_number", "status", "priority", "reason"),
            module=MODULE,
            ask_intent="ask_requisitions",
            ask_description="Answer a grounded question using material requisition records as references.",
            ask_permission=P_ASK,
            citation_prefix="requisition",
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_material_requisition",
            description="Create a material requisition draft.",
            permission=P_CREATE,
            target_action="create_material_requisition",
            method="POST",
            endpoint=API_PREFIX,
            required=("needed_by_date", "reason"),
            item_builder=requisition_items_from_slots,
            fields=(
                PayloadField("department_id", aliases=("department",), kind="int"),
                PayloadField("needed_by_date", aliases=("needed_date", "date")),
                PayloadField("reason", aliases=("description",)),
                PayloadField("priority", kind="enum", enum_values=tuple(item.value for item in MaterialRequisitionPriority), default=MaterialRequisitionPriority.NORMAL.value),
                PayloadField("notes"),
            ),
        ),
        WriteSpec(
            intent="update_material_requisition",
            description="Update an existing material requisition draft.",
            permission=P_UPDATE,
            target_action="update_material_requisition",
            method="PATCH",
            endpoint=f"{API_PREFIX}/{{entity_id}}",
            id_aliases=("requisition_id", "material_requisition_id", "id"),
            fields=(
                PayloadField("department_id", aliases=("department",), kind="int"),
                PayloadField("needed_by_date", aliases=("needed_date", "date")),
                PayloadField("reason", aliases=("description",)),
                PayloadField("priority", kind="enum", enum_values=tuple(item.value for item in MaterialRequisitionPriority)),
                PayloadField("notes"),
            ),
        ),
    )


def register() -> RequisitionAssistantToolSet:
    toolset = RequisitionAssistantToolSet()
    register_toolset(toolset)
    return toolset


register()
