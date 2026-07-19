from __future__ import annotations

from sqlalchemy import or_

from material_management.models import Item, Unit

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.assistant_resources import register_shared_assistant_resources
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, ReferenceFieldSpec, SearchSpec, WriteSpec

from . import assistant_prompt
from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchasePhase,
    PurchasePhaseAllocation,
)
from .search.service import search_purchase_order_hits
from .services import _tenant_id

MODULE = "purchase_management"
API_PREFIX = "/purchase/orders"

P_READ = "purchase_management:orders:read"
P_SEARCH = "purchase_management:orders:search"
P_ASK = "purchase_management:orders:ask"
P_CREATE = "purchase_management:orders:create"
P_UPDATE = "purchase_management:orders:update"


def _search_purchase_phases_for_resolution(db, current_user, query_text, ids=None, limit=10):
    query = (
        db.query(PurchaseOrder, PurchasePhase)
        .join(PurchasePhase, PurchasePhase.purchase_order_id == PurchaseOrder.id)
        .filter(PurchaseOrder.company_id == _tenant_id(current_user))
    )
    if ids is not None:
        query = query.filter(PurchasePhase.id.in_(ids))
    text = (query_text or "").strip()
    if text:
        pattern = f"%{text}%"
        query = query.filter(or_(
            PurchaseOrder.reference_number.ilike(pattern),
            PurchaseOrder.title.ilike(pattern),
            PurchasePhase.title.ilike(pattern),
            PurchasePhase.description.ilike(pattern),
        ))
    return query.order_by(PurchaseOrder.created_at.desc(), PurchasePhase.phase_number.asc()).limit(limit).all()


def _purchase_phase_to_candidate(row) -> Candidate:
    po, phase = row
    label = f"{po.reference_number} - phase {phase.phase_number}"
    if phase.title:
        label = f"{label} - {phase.title}"
    return Candidate(
        id=phase.id,
        match_text=phase.title or po.reference_number or "",
        label=label,
        data={
            "purchase_order_id": po.id,
            "purchase_phase_id": phase.id,
            "reference_number": po.reference_number,
            "phase_number": phase.phase_number,
            "title": phase.title,
        },
    )


def _search_purchase_phase_allocations_for_resolution(
    db,
    current_user,
    query_text,
    ids=None,
    limit=10,
):
    query = (
        db.query(
            PurchaseOrder,
            PurchasePhase,
            PurchasePhaseAllocation,
            PurchaseOrderLine,
            Item,
            Unit,
        )
        .join(
            PurchasePhase,
            PurchasePhase.purchase_order_id
            == PurchaseOrder.id,
        )
        .join(
            PurchasePhaseAllocation,
            PurchasePhaseAllocation.phase_id
            == PurchasePhase.id,
        )
        .join(
            PurchaseOrderLine,
            PurchaseOrderLine.id
            == PurchasePhaseAllocation.purchase_order_line_id,
        )
        .join(
            Item,
            Item.id == PurchaseOrderLine.item_id,
        )
        .join(
            Unit,
            Unit.id == PurchaseOrderLine.unit_id,
        )
        .filter(
            PurchaseOrder.company_id
            == _tenant_id(current_user)
        )
    )

    if ids is not None:
        query = query.filter(
            PurchasePhaseAllocation.id.in_(ids)
        )

    text = (query_text or "").strip()

    if text:
        pattern = f"%{text}%"
        query = query.filter(
            or_(
                PurchaseOrder.reference_number.ilike(
                    pattern
                ),
                PurchasePhase.title.ilike(pattern),
                PurchaseOrderLine.line_description.ilike(
                    pattern
                ),
                Item.name.ilike(pattern),
                Item.item_code.ilike(pattern),
                Unit.code.ilike(pattern),
            )
        )

    return (
        query.order_by(
            PurchaseOrder.created_at.desc(),
            PurchasePhase.phase_number.asc(),
            PurchaseOrderLine.line_number.asc(),
        )
        .limit(limit)
        .all()
    )


def _purchase_phase_allocation_to_candidate(row) -> Candidate:
    (
        purchase_order,
        phase,
        allocation,
        order_line,
        item,
        unit,
    ) = row

    label = (
        f"{purchase_order.reference_number} - "
        f"phase {phase.phase_number} - "
        f"{item.item_code or item.name}"
    )

    return Candidate(
        id=allocation.id,
        match_text=(
            order_line.line_description
            or item.name
            or item.item_code
            or ""
        ),
        label=label,
        data={
            "purchase_order_id": purchase_order.id,
            "purchase_phase_id": phase.id,
            "purchase_phase_allocation_id": (
                allocation.id
            ),
            "purchase_order_line_id": (
                order_line.id
            ),
            "reference_number": (
                purchase_order.reference_number
            ),
            "phase_number": phase.phase_number,
            "line_number": order_line.line_number,
            "item_id": order_line.item_id,
            "item_name": item.name,
            "item_code": item.item_code,
            "unit_id": order_line.unit_id,
            "unit_code": unit.code,
            "allocated_quantity": (
                allocation.allocated_quantity
            ),
        },
    )


def register_purchase_resources() -> None:
    register_resource(
        ResourceSpec(
            key="purchase_phase",
            read_permission=P_READ,
            provider=FunctionSearchProvider(
                _search_purchase_phases_for_resolution,
                _purchase_phase_to_candidate,
            ),
        )
    )
    register_resource(
        ResourceSpec(
            key="purchase_phase_allocation",
            read_permission=P_READ,
            provider=FunctionSearchProvider(
                _search_purchase_phase_allocations_for_resolution,
                _purchase_phase_allocation_to_candidate,
            ),
        )
    )


def _purchase_order_required(
    payload: dict,
    slots: dict,
) -> list[str]:
    if (
        payload.get("rfq_id")
        or payload.get("rfq_query")
    ):
        return []

    if payload.get("lines"):
        return []

    return ["lines"]

class PurchaseAssistantToolSet(ConfiguredCommerceToolSet):
    module = MODULE
    module_display_title = assistant_prompt.MODULE_DISPLAY_TITLE
    module_description = assistant_prompt.MODULE_DESCRIPTION
    module_specialist_notes = assistant_prompt.MODULE_SPECIALIST_NOTES
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
            **assistant_prompt.SEARCH_PURCHASE_ORDERS,
        ),
    )
    write_specs = (
        WriteSpec(
            intent="add_purchase_order",
            description=(
                "Create a normalized purchase "
                "order draft directly or from "
                "an existing RFQ."
            ),
            permission=P_CREATE,
            target_action=(
                "create_purchase_order"
            ),
            method="POST",
            endpoint=API_PREFIX,
            validate=(
                _purchase_order_required
            ),
            reference_fields=(
                ReferenceFieldSpec(
                    field="rfq_id",
                    resource_key="rfq",
                    raw_aliases=(
                        "rfq_query",
                        "rfq_number",
                        "rfq",
                        "request_for_quotation",
                    ),
                    explicit_aliases=(
                        "rfq_id",
                    ),
                    missing_label="RFQ",
                ),
                ReferenceFieldSpec(
                    field="supplier_id",
                    resource_key="supplier",
                    raw_aliases=(
                        "supplier_query",
                        "supplier_name",
                        "supplier",
                    ),
                    explicit_aliases=(
                        "supplier_id",
                    ),
                    missing_label="supplier",
                ),
            ),
            fields=(
                PayloadField(
                    "rfq_id",
                    kind="int",
                ),
                PayloadField(
                    "rfq_query",
                    aliases=(
                        "rfq_number",
                        "rfq",
                        "request_for_quotation",
                    ),
                ),
                PayloadField("title"),
                PayloadField(
                    "supplier_id",
                    aliases=("supplier",),
                    kind="int",
                ),
                PayloadField(
                    "supplier_name"
                ),
                PayloadField(
                    "supplier_query"
                ),
                PayloadField(
                    "description"
                ),
                PayloadField(
                    "lines",
                    kind="raw",
                ),
            ),
            **assistant_prompt
            .ADD_PURCHASE_ORDER,
        ),
        WriteSpec(
            intent=(
                "update_purchase_order"
            ),
            description=(
                "Update non-commercial fields "
                "of an existing purchase order "
                "draft."
            ),
            permission=P_UPDATE,
            target_action=(
                "update_purchase_order"
            ),
            method="PATCH",
            endpoint=(
                f"{API_PREFIX}/"
                "{entity_id}"
            ),
            id_aliases=(
                "purchase_order_id",
                "po_id",
                "id",
            ),
            reference_fields=(
                ReferenceFieldSpec(
                    field="supplier_id",
                    resource_key="supplier",
                    raw_aliases=(
                        "supplier_query",
                        "supplier_name",
                        "supplier",
                    ),
                    explicit_aliases=(
                        "supplier_id",
                    ),
                    missing_label="supplier",
                ),
            ),
            fields=(
                PayloadField("title"),
                PayloadField(
                    "supplier_id",
                    aliases=("supplier",),
                    kind="int",
                ),
                PayloadField(
                    "supplier_name"
                ),
                PayloadField(
                    "description"
                ),
                PayloadField(
                    "status",
                    kind="enum",
                    enum_values=tuple(
                        item.value
                        for item in (
                            PurchaseOrderStatus
                        )
                    ),
                ),
            ),
            **assistant_prompt
            .UPDATE_PURCHASE_ORDER,
        ),
    )

    def build_draft(self, *, intent: str, db, user, slots: dict, attachments: list):
        draft = super().build_draft(
            intent=intent,
            db=db,
            user=user,
            slots=slots,
            attachments=attachments,
        )

        if draft.payload.get("supplier_id") is not None:
            draft.payload.pop(
                "supplier_name",
                None,
            )
            draft.payload.pop(
                "supplier_query",
                None,
            )

        if intent != "add_purchase_order" or not draft.valid:
            return draft
        rfq_id = draft.payload.get("rfq_id")
        if rfq_id is None:
            return draft
        draft.payload = {}
        draft.commit_target = {
            "method": "POST",
            "endpoint": f"{API_PREFIX}/from-rfq/{rfq_id}",
            "permission": P_CREATE,
            "additional_permissions": ["rfq_management:read"],
            "entity_id": rfq_id,
        }
        return draft


def register() -> PurchaseAssistantToolSet:
    toolset = PurchaseAssistantToolSet()
    register_toolset(toolset)
    register_shared_assistant_resources()
    register_purchase_resources()
    return toolset


register()
