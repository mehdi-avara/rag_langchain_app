from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, SearchSpec, WriteSpec

from .models import SupplierStatus, SupplierType
from .search.service import search_supplier_hits

MODULE = "supplier_management"
API_PREFIX = "/supplier_management"

P_READ = "supplier_management:read"
P_SEARCH = "supplier_management:search"
P_ASK = "supplier_management:ask"
P_CREATE = "supplier_management:create"
P_UPDATE = "supplier_management:update"


def _search_suppliers_for_resolution(db, current_user, query_text, ids=None, limit=10):
    return search_supplier_hits(
        db=db,
        current_user=current_user,
        query_text=query_text,
        mode="hybrid",
        supplier_ids=ids,
        limit=limit,
    )


def _supplier_to_candidate(supplier) -> Candidate:
    code = getattr(supplier, "code", None)
    name = getattr(supplier, "name", None)
    status = getattr(supplier, "status", None)
    label = " - ".join(part for part in (code, name, status) if part)
    return Candidate(
        id=supplier.supplier_id,
        match_text=name or code or "",
        label=label or f"Supplier #{supplier.supplier_id}",
        data=supplier.model_dump(mode="json") if hasattr(supplier, "model_dump") else {
            "supplier_id": supplier.supplier_id,
            "code": code,
            "name": name,
            "status": status,
        },
    )


def register_supplier_resources() -> None:
    register_resource(ResourceSpec(
        key="supplier",
        read_permission=P_SEARCH,
        provider=FunctionSearchProvider(_search_suppliers_for_resolution, _supplier_to_candidate),
        create_permission=P_CREATE,
        create_endpoint=f"{API_PREFIX}/suppliers",
        suggestion_from=lambda raw, slots: {"name": raw},
    ))


class SupplierAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    search_specs = (
        SearchSpec(
            intent="search_suppliers",
            description="Find suppliers by name, code, type, status, country, city, or notes.",
            permission=P_SEARCH,
            search_fn=search_supplier_hits,
            resource_type="supplier",
            id_attr="supplier_id",
            id_param="supplier_ids",
            title_fields=("code", "name", "supplier_type", "status"),
            module=MODULE,
            ask_intent="ask_suppliers",
            ask_description="Answer a grounded question using supplier records as references.",
            ask_permission=P_ASK,
            citation_prefix="supplier",
            extra_params={
                "supplier_status": ("str", "status"),
                "supplier_type": ("str",),
            },
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_supplier",
            description="Create a supplier draft.",
            permission=P_CREATE,
            target_action="create_supplier",
            method="POST",
            endpoint=f"{API_PREFIX}/suppliers",
            required=("name",),
            fields=(
                PayloadField("name", aliases=("supplier_name",)),
                PayloadField("supplier_type", kind="enum", enum_values=tuple(item.value for item in SupplierType), default=SupplierType.LOCAL.value),
                PayloadField("country"),
                PayloadField("city"),
                PayloadField("address"),
                PayloadField("tax_id"),
                PayloadField("website"),
                PayloadField("status", kind="enum", enum_values=tuple(item.value for item in SupplierStatus), default=SupplierStatus.PENDING.value),
                PayloadField("notes", aliases=("description",)),
            ),
        ),
        WriteSpec(
            intent="update_supplier",
            description="Update an existing supplier draft.",
            permission=P_UPDATE,
            target_action="update_supplier",
            method="PATCH",
            endpoint=f"{API_PREFIX}/suppliers/{{entity_id}}",
            id_aliases=("supplier_id", "id"),
            fields=(
                PayloadField("name", aliases=("supplier_name",)),
                PayloadField("supplier_type", kind="enum", enum_values=tuple(item.value for item in SupplierType)),
                PayloadField("country"),
                PayloadField("city"),
                PayloadField("address"),
                PayloadField("tax_id"),
                PayloadField("website"),
                PayloadField("status", kind="enum", enum_values=tuple(item.value for item in SupplierStatus)),
                PayloadField("notes", aliases=("description",)),
            ),
        ),
    )


def register() -> SupplierAssistantToolSet:
    toolset = SupplierAssistantToolSet()
    register_toolset(toolset)
    register_supplier_resources()
    return toolset


register()
