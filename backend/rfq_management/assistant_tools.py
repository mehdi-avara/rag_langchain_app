from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.commerce_assistant import (
    ConfiguredCommerceToolSet,
    PayloadField,
    ReferenceFieldSpec,
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


def _search_rfqs_for_resolution(db, current_user, query_text, ids=None, limit=10):
    return search_rfq_hits(
        db=db,
        current_user=current_user,
        query_text=query_text,
        mode="hybrid",
        rfq_ids=ids,
        limit=limit,
    )


def _rfq_to_candidate(rfq) -> Candidate:
    number = getattr(rfq, "rfq_number", None)
    title = getattr(rfq, "title", None)
    status = getattr(rfq, "status", None)
    label = " - ".join(part for part in (number, title, status) if part)
    return Candidate(
        id=rfq.rfq_id,
        match_text=number or title or "",
        label=label or f"RFQ #{rfq.rfq_id}",
        data=rfq.model_dump(mode="json") if hasattr(rfq, "model_dump") else {
            "rfq_id": rfq.rfq_id,
            "rfq_number": number,
            "title": title,
            "status": status,
        },
    )


def register_rfq_resources() -> None:
    register_resource(ResourceSpec(
        key="rfq",
        read_permission=P_SEARCH,
        provider=FunctionSearchProvider(_search_rfqs_for_resolution, _rfq_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=API_PREFIX,
        suggestion_from=lambda raw, slots: {"title": raw},
    ))


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
            reference_fields=(
                ReferenceFieldSpec(
                    field="mr_id",
                    resource_key="material_requisition",
                    raw_aliases=("mr_query", "mr_number", "requisition_query", "requisition", "material_requisition"),
                    explicit_aliases=("mr_id", "requisition_id", "material_requisition_id"),
                    missing_label="material requisition",
                ),
                ReferenceFieldSpec(
                    field="supplier_ids",
                    resource_key="supplier",
                    raw_aliases=("supplier_query", "supplier_name", "supplier"),
                    explicit_aliases=("supplier_id",),
                    missing_label="supplier",
                    as_list=True,
                ),
                ReferenceFieldSpec(
                    field="item_id",
                    resource_key="material_item",
                    raw_aliases=("item_query", "item_name", "item", "material_item", "part", "part_name"),
                    explicit_aliases=("item_id", "material_item_id"),
                    missing_label="item",
                    collection="items",
                ),
            ),
            fields=(
                PayloadField("mr_id", aliases=("requisition_id", "material_requisition_id"), kind="int"),
                PayloadField("title"),
                PayloadField("description"),
                PayloadField("deadline_date", aliases=("deadline", "date")),
                PayloadField("supplier_ids", aliases=("suppliers",), kind="raw", default=[]),
                PayloadField("supplier_query", aliases=("supplier_name", "supplier")),
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
    register_rfq_resources()
    return toolset


register()
