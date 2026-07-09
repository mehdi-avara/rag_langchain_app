from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.assistant_resources import register_shared_assistant_resources
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    ReferenceFieldSpec,
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


def _search_requisitions_for_resolution(db, current_user, query_text, ids=None, limit=10):
    return search_requisition_hits(
        db=db,
        current_user=current_user,
        query_text=query_text,
        mode="hybrid",
        requisition_ids=ids,
        limit=limit,
    )


def _requisition_to_candidate(requisition) -> Candidate:
    number = getattr(requisition, "mr_number", None)
    reason = getattr(requisition, "reason", None)
    status = getattr(requisition, "status", None)
    label = " - ".join(part for part in (number, status, reason) if part)
    return Candidate(
        id=requisition.requisition_id,
        match_text=number or reason or "",
        label=label or f"MR #{requisition.requisition_id}",
        data=requisition.model_dump(mode="json") if hasattr(requisition, "model_dump") else {
            "requisition_id": requisition.requisition_id,
            "mr_number": number,
            "reason": reason,
            "status": status,
        },
    )


def register_requisition_resources() -> None:
    register_resource(ResourceSpec(
        key="material_requisition",
        read_permission=P_SEARCH,
        provider=FunctionSearchProvider(_search_requisitions_for_resolution, _requisition_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=API_PREFIX,
        suggestion_from=lambda raw, slots: {"reason": raw},
    ))


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
            reference_fields=(
                ReferenceFieldSpec(
                    field="item_id",
                    resource_key="material_item",
                    raw_aliases=("item_query", "item_name", "item", "material_item", "part", "part_name"),
                    explicit_aliases=("item_id", "material_item_id"),
                    missing_label="item",
                    collection="items",
                ),
                ReferenceFieldSpec(
                    field="currency_id",
                    resource_key="currency",
                    raw_aliases=("currency_query", "currency_code", "currency"),
                    explicit_aliases=("currency_id",),
                    missing_label="currency",
                    collection="items",
                ),
                ReferenceFieldSpec(
                    field="base_currency_id",
                    resource_key="currency",
                    raw_aliases=("base_currency_query", "base_currency_code", "base_currency"),
                    explicit_aliases=("base_currency_id",),
                    missing_label="base currency",
                    collection="items",
                ),
            ),
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
    register_shared_assistant_resources()
    register_requisition_resources()
    return toolset


register()
