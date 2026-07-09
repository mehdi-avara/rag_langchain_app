from __future__ import annotations

from sqlalchemy import or_

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from assistant.registry import register_toolset
from shared.commerce_assistant import ConfiguredCommerceToolSet, PayloadField, ReferenceFieldSpec, SearchSpec, WriteSpec

from .models import PurchaseOrder, PurchaseOrderStatus, PurchasePhase, PurchasePhaseItem
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


def _search_purchase_phase_items_for_resolution(db, current_user, query_text, ids=None, limit=10):
    query = (
        db.query(PurchaseOrder, PurchasePhase, PurchasePhaseItem)
        .join(PurchasePhase, PurchasePhase.purchase_order_id == PurchaseOrder.id)
        .join(PurchasePhaseItem, PurchasePhaseItem.phase_id == PurchasePhase.id)
        .filter(PurchaseOrder.company_id == _tenant_id(current_user))
    )
    if ids is not None:
        query = query.filter(PurchasePhaseItem.id.in_(ids))
    text = (query_text or "").strip()
    if text:
        pattern = f"%{text}%"
        query = query.filter(or_(
            PurchaseOrder.reference_number.ilike(pattern),
            PurchasePhase.title.ilike(pattern),
            PurchasePhaseItem.item_name.ilike(pattern),
            PurchasePhaseItem.item_code.ilike(pattern),
        ))
    return query.order_by(PurchaseOrder.created_at.desc(), PurchasePhase.phase_number.asc()).limit(limit).all()


def _purchase_phase_item_to_candidate(row) -> Candidate:
    po, phase, item = row
    label = f"{po.reference_number} - phase {phase.phase_number} - {item.item_code or item.item_name}"
    return Candidate(
        id=item.id,
        match_text=item.item_name or item.item_code or "",
        label=label,
        data={
            "purchase_order_id": po.id,
            "purchase_phase_id": phase.id,
            "purchase_phase_item_id": item.id,
            "reference_number": po.reference_number,
            "phase_number": phase.phase_number,
            "item_name": item.item_name,
            "item_code": item.item_code,
        },
    )


def register_purchase_resources() -> None:
    register_resource(ResourceSpec(
        key="purchase_phase",
        read_permission=P_READ,
        provider=FunctionSearchProvider(_search_purchase_phases_for_resolution, _purchase_phase_to_candidate),
    ))
    register_resource(ResourceSpec(
        key="purchase_phase_item",
        read_permission=P_READ,
        provider=FunctionSearchProvider(_search_purchase_phase_items_for_resolution, _purchase_phase_item_to_candidate),
    ))


def _purchase_order_required(payload: dict, slots: dict) -> list[str]:
    if payload.get("rfq_id") or payload.get("rfq_query"):
        return []
    missing: list[str] = []
    if payload.get("currency_id") is None:
        missing.append("currency_id")
    if payload.get("base_currency_id") is None:
        missing.append("base_currency_id")
    return missing


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
            description="Create a purchase order draft, either directly or from an existing RFQ.",
            permission=P_CREATE,
            target_action="create_purchase_order",
            method="POST",
            endpoint=API_PREFIX,
            validate=_purchase_order_required,
            reference_fields=(
                ReferenceFieldSpec(
                    field="rfq_id",
                    resource_key="rfq",
                    raw_aliases=("rfq_query", "rfq_number", "rfq", "request_for_quotation"),
                    explicit_aliases=("rfq_id",),
                    missing_label="RFQ",
                ),
                ReferenceFieldSpec(
                    field="supplier_id",
                    resource_key="supplier",
                    raw_aliases=("supplier_query", "supplier_name", "supplier"),
                    explicit_aliases=("supplier_id",),
                    missing_label="supplier",
                ),
            ),
            fields=(
                PayloadField("rfq_id", kind="int"),
                PayloadField("rfq_query", aliases=("rfq_number", "rfq", "request_for_quotation")),
                PayloadField("title"),
                PayloadField("supplier_id", aliases=("supplier",), kind="int"),
                PayloadField("supplier_name"),
                PayloadField("supplier_query"),
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

    def build_draft(self, *, intent: str, db, user, slots: dict, attachments: list):
        draft = super().build_draft(intent=intent, db=db, user=user, slots=slots, attachments=attachments)
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
    register_purchase_resources()
    return toolset


register()
