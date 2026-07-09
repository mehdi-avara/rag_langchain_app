from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

import Models

from goods_receipt_management.models import GoodsReceiptItem, GoodsReceiptNote
from purchase_management.models import PurchaseOrder, PurchasePhase, PurchasePhaseItem
from requisition_management.models import (
    MaterialRequisition,
    MaterialRequisitionStatusHistory,
)
from rfq_management.models import (
    QuotationResponse,
    QuotationResponseItem,
    RequestForQuotation,
    RFQItem,
    RFQSupplier,
)
from warehouse_management.models import (
    StockItem,
    StockMovement,
    StorageLocation,
    Warehouse,
    Zone,
)

from .schemas import (
    BusinessFlowConnection,
    BusinessFlowNode,
    BusinessFlowResponse,
    BusinessFlowRoot,
    BusinessFlowTimelineEvent,
)


class BusinessFlowNotFound(Exception):
    pass


AUDIT_COVERAGE = {
    "mr": "actual",
    "rfq": "partial",
    "quotation": "partial",
    "po": "inferred",
    "grn": "partial",
    "stock_movement": "actual",
}


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_clean(item) for item in value]

    return value


def _details(**values: Any) -> dict[str, Any]:
    return _clean({key: value for key, value in values.items()})


class BusinessFlowBuilder:
    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self.nodes: dict[str, BusinessFlowNode] = {}
        self.connections: dict[str, BusinessFlowConnection] = {}
        self.timeline: dict[str, BusinessFlowTimelineEvent] = {}

    def response(self, root_type: str, root_id: int) -> BusinessFlowResponse:
        return BusinessFlowResponse(
            root=BusinessFlowRoot(type=root_type, id=root_id),
            audit_coverage=AUDIT_COVERAGE,
            nodes=list(self.nodes.values()),
            connections=list(self.connections.values()),
            timeline=sorted(
                self.timeline.values(),
                key=lambda item: (
                    item.changed_at or item.created_at or datetime.min,
                    item.id,
                ),
            ),
        )

    def node(
        self,
        *,
        id: str,
        kind: str,
        state: str,
        title: str,
        source: str,
        description: str | None = None,
        is_inferred: bool = False,
        route: str | None = None,
        actor_user_id: int | None = None,
        created_at: datetime | None = None,
        changed_at: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if id in self.nodes:
            return

        self.nodes[id] = BusinessFlowNode(
            id=id,
            kind=kind,
            state=state,
            title=title,
            description=description,
            source=source,
            is_inferred=is_inferred,
            route=route,
            actor_user_id=actor_user_id,
            created_at=created_at,
            changed_at=changed_at,
            details=details or {},
        )

    def connect(
        self,
        from_node_id: str,
        to_node_id: str,
        *,
        label: str | None = None,
        source: str,
        is_inferred: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        id = f"connection:{from_node_id}:{to_node_id}"

        if id in self.connections:
            return

        self.connections[id] = BusinessFlowConnection(
            id=id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            label=label,
            source=source,
            is_inferred=is_inferred,
            details=details or {},
        )

    def event(
        self,
        *,
        id: str,
        kind: str,
        state: str,
        title: str,
        source: str,
        entity_type: str,
        entity_id: int | None = None,
        description: str | None = None,
        is_inferred: bool = False,
        actor_user_id: int | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        created_at: datetime | None = None,
        changed_at: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if id in self.timeline:
            return

        self.timeline[id] = BusinessFlowTimelineEvent(
            id=id,
            kind=kind,
            state=state,
            title=title,
            description=description,
            source=source,
            is_inferred=is_inferred,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            from_status=from_status,
            to_status=to_status,
            created_at=created_at,
            changed_at=changed_at,
            details=details or {},
        )

    def get_mr(self, mr_id: int) -> MaterialRequisition:
        row = (
            self.db.query(MaterialRequisition)
            .filter(
                MaterialRequisition.id == mr_id,
                MaterialRequisition.company_id == self.company_id,
            )
            .first()
        )

        if row is None:
            raise BusinessFlowNotFound("material_requisition_not_found")

        return row

    def get_rfq(self, rfq_id: int) -> RequestForQuotation:
        row = (
            self.db.query(RequestForQuotation)
            .filter(
                RequestForQuotation.id == rfq_id,
                RequestForQuotation.company_id == self.company_id,
            )
            .first()
        )

        if row is None:
            raise BusinessFlowNotFound("rfq_not_found")

        return row

    def get_po(self, po_id: int) -> PurchaseOrder:
        row = (
            self.db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.id == po_id,
                PurchaseOrder.company_id == self.company_id,
            )
            .first()
        )

        if row is None:
            raise BusinessFlowNotFound("purchase_order_not_found")

        return row

    def get_grn(self, grn_id: int) -> GoodsReceiptNote:
        row = (
            self.db.query(GoodsReceiptNote)
            .filter(
                GoodsReceiptNote.id == grn_id,
                GoodsReceiptNote.company_id == self.company_id,
            )
            .first()
        )

        if row is None:
            raise BusinessFlowNotFound("goods_receipt_not_found")

        return row

    def get_stock_movement(self, movement_id: int) -> StockMovement:
        row = (
            self.db.query(StockMovement)
            .filter(
                StockMovement.id == movement_id,
                StockMovement.company_id == self.company_id,
            )
            .first()
        )

        if row is None:
            raise BusinessFlowNotFound("stock_movement_not_found")

        return row

    def add_mr(self, mr: MaterialRequisition) -> None:
        mr_node_id = f"mr:{mr.id}"

        self.node(
            id=mr_node_id,
            kind="mr",
            state=mr.status,
            title=mr.mr_number,
            description=mr.reason,
            source="record",
            route=f"/requisitions/{mr.id}",
            actor_user_id=mr.requested_by_user_id,
            created_at=mr.created_at,
            details=_details(
                id=mr.id,
                mr_number=mr.mr_number,
                priority=mr.priority,
                needed_by_date=mr.needed_by_date,
                requested_by_user_id=mr.requested_by_user_id,
                item_count=len(mr.items),
            ),
        )

        self.event(
            id=f"timeline:mr:{mr.id}:created",
            kind="mr",
            state=mr.status,
            title="Material requisition created",
            source="record",
            entity_type="mr",
            entity_id=mr.id,
            actor_user_id=mr.requested_by_user_id,
            created_at=mr.created_at,
            details=_details(mr_number=mr.mr_number),
        )

        histories = (
            self.db.query(MaterialRequisitionStatusHistory)
            .filter(MaterialRequisitionStatusHistory.material_requisition_id == mr.id)
            .order_by(MaterialRequisitionStatusHistory.changed_at.asc())
            .all()
        )

        previous_node_id = mr_node_id

        for history in histories:
            history_node_id = f"mr_status:{mr.id}:{history.id}"

            self.node(
                id=history_node_id,
                kind="mr_status",
                state=history.to_status,
                title=f"MR {history.action}",
                description=history.note,
                source="audit",
                route=f"/requisitions/{mr.id}",
                actor_user_id=history.changed_by_user_id,
                changed_at=history.changed_at,
                details=_details(
                    history_id=history.id,
                    from_status=history.from_status,
                    to_status=history.to_status,
                    action=history.action,
                    note=history.note,
                ),
            )

            self.connect(
                previous_node_id,
                history_node_id,
                label=history.action,
                source="audit",
                details=_details(
                    history_id=history.id,
                    from_status=history.from_status,
                    to_status=history.to_status,
                ),
            )

            self.event(
                id=f"timeline:mr_status:{mr.id}:{history.id}",
                kind="mr_status",
                state=history.to_status,
                title=f"MR status changed to {history.to_status}",
                description=history.note,
                source="audit",
                entity_type="mr",
                entity_id=mr.id,
                actor_user_id=history.changed_by_user_id,
                from_status=history.from_status,
                to_status=history.to_status,
                changed_at=history.changed_at,
                details=_details(action=history.action),
            )

            previous_node_id = history_node_id

    def add_rfq(self, rfq: RequestForQuotation, include_downstream: bool = True) -> None:
        rfq_node_id = f"rfq:{rfq.id}"

        self.node(
            id=rfq_node_id,
            kind="rfq",
            state=rfq.status,
            title=rfq.rfq_number,
            description=rfq.title,
            source="record",
            route=f"/rfqs/{rfq.id}",
            actor_user_id=rfq.created_by_user_id,
            created_at=rfq.created_at,
            details=_details(
                id=rfq.id,
                rfq_number=rfq.rfq_number,
                mr_id=rfq.mr_id,
                deadline_date=rfq.deadline_date,
                created_by_user_id=rfq.created_by_user_id,
            ),
        )

        self.event(
            id=f"timeline:rfq:{rfq.id}:created",
            kind="rfq",
            state=rfq.status,
            title="RFQ created",
            source="record",
            entity_type="rfq",
            entity_id=rfq.id,
            actor_user_id=rfq.created_by_user_id,
            created_at=rfq.created_at,
            details=_details(rfq_number=rfq.rfq_number),
        )

        if rfq.mr_id:
            self.connect(
                f"mr:{rfq.mr_id}",
                rfq_node_id,
                label="RFQ created from MR",
                source="record",
                details=_details(mr_id=rfq.mr_id, rfq_id=rfq.id),
            )

        suppliers = (
            self.db.query(RFQSupplier)
            .filter(RFQSupplier.rfq_id == rfq.id)
            .order_by(RFQSupplier.id.asc())
            .all()
        )
        supplier_node_by_supplier_id: dict[int, str] = {}

        for supplier in suppliers:
            supplier_node_id = f"supplier:{supplier.id}"

            if supplier.supplier_id is not None:
                supplier_node_by_supplier_id[supplier.supplier_id] = supplier_node_id

            self.node(
                id=supplier_node_id,
                kind="supplier",
                state=supplier.response_status,
                title=supplier.supplier_name,
                description=supplier.supplier_code,
                source="record",
                created_at=supplier.created_at,
                changed_at=supplier.sent_at,
                details=_details(
                    rfq_supplier_id=supplier.id,
                    supplier_id=supplier.supplier_id,
                    supplier_code=supplier.supplier_code,
                    response_status=supplier.response_status,
                    sent_at=supplier.sent_at,
                ),
            )

            self.connect(
                rfq_node_id,
                supplier_node_id,
                label="Supplier invited",
                source="record",
                details=_details(rfq_supplier_id=supplier.id),
            )

            if supplier.sent_at is not None:
                self.event(
                    id=f"timeline:supplier:{supplier.id}:sent",
                    kind="supplier",
                    state="sent",
                    title="RFQ sent to supplier",
                    source="record",
                    entity_type="rfq_supplier",
                    entity_id=supplier.id,
                    changed_at=supplier.sent_at,
                    details=_details(
                        rfq_id=rfq.id,
                        supplier_id=supplier.supplier_id,
                        supplier_name=supplier.supplier_name,
                    ),
                )

        rfq_items = (
            self.db.query(RFQItem)
            .filter(RFQItem.rfq_id == rfq.id)
            .order_by(RFQItem.id.asc())
            .all()
        )

        responses = (
            self.db.query(QuotationResponse)
            .filter(QuotationResponse.rfq_id == rfq.id)
            .order_by(QuotationResponse.received_at.asc(), QuotationResponse.id.asc())
            .all()
        )

        response_ids = [response.id for response in responses]
        quote_items = (
            self.db.query(QuotationResponseItem)
            .filter(QuotationResponseItem.quotation_response_id.in_(response_ids))
            .order_by(QuotationResponseItem.id.asc())
            .all()
            if response_ids
            else []
        )

        quote_items_by_response: dict[int, list[QuotationResponseItem]] = {}

        for item in quote_items:
            quote_items_by_response.setdefault(item.quotation_response_id, []).append(item)

        if responses:
            comparison_node_id = f"comparison:rfq:{rfq.id}"

            self.node(
                id=comparison_node_id,
                kind="comparison",
                state="current",
                title="Quotation comparison",
                description="Supplier quotations available for comparison.",
                source="record",
                route=f"/rfqs/{rfq.id}/comparison",
                details=_details(
                    rfq_id=rfq.id,
                    quotation_count=len(responses),
                    rfq_item_count=len(rfq_items),
                ),
            )

            self.connect(
                rfq_node_id,
                comparison_node_id,
                label="Compare quotations",
                source="record",
                details=_details(rfq_id=rfq.id),
            )

        for response in responses:
            quotation_node_id = f"quotation:{response.id}"
            supplier_source_node_id = (
                supplier_node_by_supplier_id.get(response.supplier_id)
                if response.supplier_id is not None
                else None
            )

            self.node(
                id=quotation_node_id,
                kind="quotation",
                state="winner" if response.is_winner else "received",
                title=response.supplier_name,
                description=response.notes,
                source="record",
                route=f"/rfqs/{rfq.id}/responses",
                created_at=response.created_at,
                changed_at=response.received_at,
                details=_details(
                    quotation_response_id=response.id,
                    rfq_id=response.rfq_id,
                    supplier_id=response.supplier_id,
                    supplier_code=response.supplier_code,
                    received_at=response.received_at,
                    valid_until=response.valid_until,
                    delivery_days=response.delivery_days,
                    is_winner=response.is_winner,
                    selected_by_user_id=response.selected_by_user_id,
                    selected_at=response.selected_at,
                ),
            )

            self.connect(
                supplier_source_node_id or rfq_node_id,
                quotation_node_id,
                label="Quotation received",
                source="record",
                details=_details(quotation_response_id=response.id),
            )

            if responses:
                self.connect(
                    quotation_node_id,
                    f"comparison:rfq:{rfq.id}",
                    label="Included in comparison",
                    source="record",
                    details=_details(quotation_response_id=response.id),
                )

            self.event(
                id=f"timeline:quotation:{response.id}:received",
                kind="quotation",
                state="received",
                title="Quotation response received",
                source="record",
                entity_type="quotation",
                entity_id=response.id,
                changed_at=response.received_at,
                details=_details(
                    rfq_id=rfq.id,
                    supplier_id=response.supplier_id,
                    supplier_name=response.supplier_name,
                ),
            )

            for quote_item in quote_items_by_response.get(response.id, []):
                quote_item_node_id = f"quotation_item:{quote_item.id}"

                self.node(
                    id=quote_item_node_id,
                    kind="quotation_item",
                    state="current",
                    title=f"Quoted item {quote_item.rfq_item_id}",
                    description=quote_item.notes,
                    source="record",
                    created_at=quote_item.created_at,
                    details=_details(
                        quotation_response_item_id=quote_item.id,
                        quotation_response_id=quote_item.quotation_response_id,
                        rfq_item_id=quote_item.rfq_item_id,
                        unit_price=quote_item.unit_price,
                        currency_id=quote_item.currency_id,
                        unit_price_base=quote_item.unit_price_base,
                        lead_time_days=quote_item.lead_time_days,
                    ),
                )

                self.connect(
                    quotation_node_id,
                    quote_item_node_id,
                    label="Quoted line",
                    source="record",
                    details=_details(quotation_response_item_id=quote_item.id),
                )

            if response.is_winner:
                winner_node_id = f"winner:{response.id}"

                self.node(
                    id=winner_node_id,
                    kind="winner",
                    state="winner",
                    title=f"Winning quotation: {response.supplier_name}",
                    description="This quotation is marked as the selected winner.",
                    source="record",
                    route=f"/rfqs/{rfq.id}/comparison",
                    actor_user_id=response.selected_by_user_id,
                    changed_at=response.selected_at,
                    details=_details(
                        quotation_response_id=response.id,
                        rfq_id=rfq.id,
                        supplier_id=response.supplier_id,
                        selected_by_user_id=response.selected_by_user_id,
                        selected_at=response.selected_at,
                    ),
                )

                self.connect(
                    quotation_node_id,
                    winner_node_id,
                    label="Selected as winner",
                    source="record",
                    details=_details(quotation_response_id=response.id),
                )

                if responses:
                    self.connect(
                        f"comparison:rfq:{rfq.id}",
                        winner_node_id,
                        label="Winner selected",
                        source="record",
                        details=_details(quotation_response_id=response.id),
                    )

                self.event(
                    id=f"timeline:winner:{response.id}",
                    kind="winner",
                    state="winner",
                    title="Winning quotation selected",
                    source="record",
                    entity_type="quotation",
                    entity_id=response.id,
                    actor_user_id=response.selected_by_user_id,
                    changed_at=response.selected_at,
                    details=_details(
                        rfq_id=rfq.id,
                        supplier_id=response.supplier_id,
                        supplier_name=response.supplier_name,
                    ),
                )

        if include_downstream:
            po = (
                self.db.query(PurchaseOrder)
                .filter(
                    PurchaseOrder.company_id == self.company_id,
                    PurchaseOrder.rfq_id == rfq.id,
                )
                .first()
            )

            if po is not None:
                self.add_po(po, include_upstream=False)

    def add_po(self, po: PurchaseOrder, include_upstream: bool = True) -> None:
        po_node_id = f"po:{po.id}"

        self.node(
            id=po_node_id,
            kind="po",
            state=po.status,
            title=po.reference_number,
            description=po.title or po.description,
            source="record",
            route=f"/purchase/orders/{po.id}",
            actor_user_id=po.created_by_user_id,
            created_at=po.created_at,
            details=_details(
                id=po.id,
                reference_number=po.reference_number,
                rfq_id=po.rfq_id,
                winning_quotation_response_id=po.winning_quotation_response_id,
                supplier_id=po.supplier_id,
                supplier_name=po.supplier_name,
                status=po.status,
                approval_status=po.approval_status,
                approved_by_user_id=po.approved_by_user_id,
            ),
        )

        self.event(
            id=f"timeline:po:{po.id}:created",
            kind="po",
            state=po.status,
            title="Purchase order created",
            source="record",
            entity_type="po",
            entity_id=po.id,
            actor_user_id=po.created_by_user_id,
            created_at=po.created_at,
            details=_details(reference_number=po.reference_number),
        )

        if include_upstream and po.rfq_id:
            rfq = (
                self.db.query(RequestForQuotation)
                .filter(
                    RequestForQuotation.id == po.rfq_id,
                    RequestForQuotation.company_id == self.company_id,
                )
                .first()
            )

            if rfq is not None:
                if rfq.mr_id:
                    mr = (
                        self.db.query(MaterialRequisition)
                        .filter(
                            MaterialRequisition.id == rfq.mr_id,
                            MaterialRequisition.company_id == self.company_id,
                        )
                        .first()
                    )

                    if mr is not None:
                        self.add_mr(mr)

                self.add_rfq(rfq, include_downstream=False)

        if po.rfq_id:
            self.connect(
                f"rfq:{po.rfq_id}",
                po_node_id,
                label="Purchase order created from RFQ",
                source="record",
                details=_details(po_id=po.id, rfq_id=po.rfq_id),
            )
        else:
            skipped_node_id = f"skipped:rfq:po:{po.id}"

            self.node(
                id=skipped_node_id,
                kind="skipped",
                state="skipped",
                title="RFQ skipped",
                description="This purchase order was created manually without an RFQ.",
                source="record",
                is_inferred=False,
                details=_details(po_id=po.id),
            )

            self.connect(
                skipped_node_id,
                po_node_id,
                label="Manual purchase order",
                source="record",
                details=_details(po_id=po.id),
            )

        approval_node_id = f"po_approval:{po.id}"

        self.node(
            id=approval_node_id,
            kind="po_approval",
            state=po.approval_status,
            title="Current PO approval status",
            description="This node shows the current approval status. Detailed approval history is not stored yet.",
            source="record",
            is_inferred=False,
            actor_user_id=po.approved_by_user_id,
            details=_details(
                po_id=po.id,
                approval_status=po.approval_status,
                approved_by_user_id=po.approved_by_user_id,
            ),
        )

        self.connect(
            po_node_id,
            approval_node_id,
            label="Current approval status",
            source="record",
            details=_details(approval_status=po.approval_status),
        )

        phases = (
            self.db.query(PurchasePhase)
            .filter(PurchasePhase.purchase_order_id == po.id)
            .order_by(PurchasePhase.phase_number.asc(), PurchasePhase.id.asc())
            .all()
        )

        phase_item_node_by_id: dict[int, str] = {}

        for phase in phases:
            phase_node_id = f"phase:{phase.id}"

            self.node(
                id=phase_node_id,
                kind="phase",
                state=phase.status,
                title=phase.title or f"Phase {phase.phase_number}",
                description=phase.description,
                source="record",
                route=f"/purchase/orders/{po.id}/phases",
                created_at=phase.created_at,
                details=_details(
                    phase_id=phase.id,
                    purchase_order_id=phase.purchase_order_id,
                    phase_number=phase.phase_number,
                    expected_delivery_date=phase.expected_delivery_date,
                    actual_delivery_date=phase.actual_delivery_date,
                ),
            )

            self.connect(
                po_node_id,
                phase_node_id,
                label="Delivery phase",
                source="record",
                details=_details(phase_id=phase.id),
            )

            items = (
                self.db.query(PurchasePhaseItem)
                .filter(PurchasePhaseItem.phase_id == phase.id)
                .order_by(PurchasePhaseItem.id.asc())
                .all()
            )

            for item in items:
                po_item_node_id = f"po_item:{item.id}"
                phase_item_node_by_id[item.id] = po_item_node_id

                self.node(
                    id=po_item_node_id,
                    kind="po_item",
                    state="current",
                    title=item.item_name,
                    description=item.notes,
                    source="record",
                    created_at=item.created_at,
                    details=_details(
                        phase_item_id=item.id,
                        phase_id=item.phase_id,
                        item_id=item.item_id,
                        item_code=item.item_code,
                        quantity=item.quantity,
                        received_quantity=item.received_quantity,
                        unit=item.unit,
                        unit_price=item.unit_price,
                        line_total=item.line_total,
                    ),
                )

                self.connect(
                    phase_node_id,
                    po_item_node_id,
                    label="PO line item",
                    source="record",
                    details=_details(phase_item_id=item.id),
                )

        self.add_grns_for_po(po, phase_item_node_by_id=phase_item_node_by_id)

    def add_grns_for_po(
        self,
        po: PurchaseOrder,
        phase_item_node_by_id: dict[int, str] | None = None,
    ) -> None:
        phase_item_node_by_id = phase_item_node_by_id or {}

        grns = (
            self.db.query(GoodsReceiptNote)
            .filter(
                GoodsReceiptNote.company_id == self.company_id,
                GoodsReceiptNote.purchase_order_id == po.id,
            )
            .order_by(GoodsReceiptNote.created_at.asc(), GoodsReceiptNote.id.asc())
            .all()
        )

        for grn in grns:
            self.add_grn(
                grn,
                include_upstream=False,
                phase_item_node_by_id=phase_item_node_by_id,
            )

    def add_grn(
        self,
        grn: GoodsReceiptNote,
        include_upstream: bool = True,
        phase_item_node_by_id: dict[int, str] | None = None,
    ) -> None:
        grn_node_id = f"grn:{grn.id}"

        self.node(
            id=grn_node_id,
            kind="grn",
            state=grn.status,
            title=grn.grn_number,
            description=grn.notes,
            source="record",
            route=f"/goods-receipts/{grn.id}",
            actor_user_id=grn.received_by_user_id,
            created_at=grn.created_at,
            details=_details(
                grn_id=grn.id,
                grn_number=grn.grn_number,
                purchase_order_id=grn.purchase_order_id,
                purchase_phase_id=grn.purchase_phase_id,
                receipt_date=grn.receipt_date,
                delivery_note_number=grn.delivery_note_number,
                warehouse_id=grn.warehouse_id,
            ),
        )

        self.event(
            id=f"timeline:grn:{grn.id}:created",
            kind="grn",
            state=grn.status,
            title="Goods receipt created",
            source="record",
            entity_type="grn",
            entity_id=grn.id,
            actor_user_id=grn.received_by_user_id,
            created_at=grn.created_at,
            details=_details(grn_number=grn.grn_number),
        )

        if include_upstream:
            po = self.get_po(grn.purchase_order_id)
            self.add_po(po, include_upstream=True)

        self.connect(
            f"po:{grn.purchase_order_id}",
            grn_node_id,
            label="Goods receipt",
            source="record",
            details=_details(grn_id=grn.id, po_id=grn.purchase_order_id),
        )

        if grn.purchase_phase_id:
            self.connect(
                f"phase:{grn.purchase_phase_id}",
                grn_node_id,
                label="Received against phase",
                source="record",
                details=_details(grn_id=grn.id, phase_id=grn.purchase_phase_id),
            )

        items = (
            self.db.query(GoodsReceiptItem)
            .filter(GoodsReceiptItem.goods_receipt_note_id == grn.id)
            .order_by(GoodsReceiptItem.id.asc())
            .all()
        )

        grn_item_ids: list[int] = []

        for item in items:
            grn_item_ids.append(item.id)
            grn_item_node_id = f"grn_item:{item.id}"

            self.node(
                id=grn_item_node_id,
                kind="grn_item",
                state="received",
                title=item.item_name,
                description=item.notes or item.rejection_reason,
                source="record",
                created_at=item.created_at,
                details=_details(
                    grn_item_id=item.id,
                    grn_id=grn.id,
                    purchase_phase_item_id=item.purchase_phase_item_id,
                    item_id=item.item_id,
                    item_code=item.item_code,
                    received_quantity=item.received_quantity,
                    accepted_quantity=item.accepted_quantity,
                    rejected_quantity=item.rejected_quantity,
                    storage_location_id=item.storage_location_id,
                    unit_cost=item.unit_cost,
                ),
            )

            self.connect(
                grn_node_id,
                grn_item_node_id,
                label="GRN line item",
                source="record",
                details=_details(grn_item_id=item.id),
            )

            po_item_node_id = (phase_item_node_by_id or {}).get(item.purchase_phase_item_id)

            if po_item_node_id:
                self.connect(
                    po_item_node_id,
                    grn_item_node_id,
                    label="Received line",
                    source="record",
                    details=_details(
                        phase_item_id=item.purchase_phase_item_id,
                        grn_item_id=item.id,
                    ),
                )

        movements = (
            self.db.query(StockMovement)
            .filter(
                StockMovement.company_id == self.company_id,
                StockMovement.reference_type == "grn",
                StockMovement.reference_id == grn.id,
            )
            .order_by(StockMovement.movement_date.asc(), StockMovement.id.asc())
            .all()
        )

        for movement in movements:
            self.add_stock_movement(movement, include_upstream=False)

        if grn.status == "posted" and not movements:
            waiting_node_id = f"waiting:stock:grn:{grn.id}"

            self.node(
                id=waiting_node_id,
                kind="blocked",
                state="waiting",
                title="Warehouse movement pending",
                description="GRN is posted, but no warehouse stock movement was found yet. Celery or backfill may still be pending.",
                source="record",
                is_inferred=False,
                details=_details(grn_id=grn.id, grn_item_ids=grn_item_ids),
            )

            self.connect(
                grn_node_id,
                waiting_node_id,
                label="Waiting for stock movement",
                source="record",
                details=_details(grn_id=grn.id),
            )

    def add_stock_movement(
        self,
        movement: StockMovement,
        include_upstream: bool = True,
    ) -> None:
        movement_node_id = f"stock_movement:{movement.id}"

        self.node(
            id=movement_node_id,
            kind="stock_movement",
            state="done",
            title=movement.movement_number,
            description=movement.notes,
            source="record",
            route="/warehouse/movements",
            actor_user_id=movement.performed_by_user_id,
            created_at=movement.created_at,
            changed_at=movement.movement_date,
            details=_details(
                stock_movement_id=movement.id,
                movement_number=movement.movement_number,
                movement_type=movement.movement_type,
                item_id=movement.item_id,
                from_location_id=movement.from_location_id,
                to_location_id=movement.to_location_id,
                quantity=movement.quantity,
                reference_type=movement.reference_type,
                reference_id=movement.reference_id,
                reference_line_id=movement.reference_line_id,
            ),
        )

        self.event(
            id=f"timeline:stock_movement:{movement.id}",
            kind="stock_movement",
            state="done",
            title="Stock movement posted",
            description=movement.notes,
            source="record",
            entity_type="stock_movement",
            entity_id=movement.id,
            actor_user_id=movement.performed_by_user_id,
            created_at=movement.created_at,
            changed_at=movement.movement_date,
            details=_details(
                movement_number=movement.movement_number,
                movement_type=movement.movement_type,
                reference_type=movement.reference_type,
                reference_id=movement.reference_id,
                reference_line_id=movement.reference_line_id,
            ),
        )

        if include_upstream and movement.reference_type == "grn":
            grn = (
                self.db.query(GoodsReceiptNote)
                .filter(
                    GoodsReceiptNote.id == movement.reference_id,
                    GoodsReceiptNote.company_id == self.company_id,
                )
                .first()
            )

            if grn is not None:
                self.add_grn(grn, include_upstream=True)

        if movement.reference_type == "grn":
            if movement.reference_line_id:
                from_node_id = f"grn_item:{movement.reference_line_id}"
            else:
                from_node_id = f"grn:{movement.reference_id}"

            self.connect(
                from_node_id,
                movement_node_id,
                label="Warehouse movement",
                source="record",
                details=_details(
                    reference_type=movement.reference_type,
                    reference_id=movement.reference_id,
                    reference_line_id=movement.reference_line_id,
                ),
            )

        location_id = movement.to_location_id or movement.from_location_id

        if location_id is not None:
            location = (
                self.db.query(StorageLocation)
                .filter(StorageLocation.id == location_id)
                .first()
            )

            if location is not None:
                zone = self.db.query(Zone).filter(Zone.id == location.zone_id).first()
                warehouse = (
                    self.db.query(Warehouse)
                    .filter(Warehouse.id == zone.warehouse_id)
                    .first()
                    if zone is not None
                    else None
                )

                if warehouse is not None:
                    warehouse_node_id = f"warehouse:{warehouse.id}"

                    self.node(
                        id=warehouse_node_id,
                        kind="warehouse",
                        state="current",
                        title=warehouse.name,
                        description=warehouse.code,
                        source="record",
                        created_at=warehouse.created_at,
                        details=_details(
                            warehouse_id=warehouse.id,
                            code=warehouse.code,
                            warehouse_type=warehouse.warehouse_type,
                            location=warehouse.location,
                            storage_location_id=location.id,
                            storage_location_code=location.code,
                            storage_location_name=location.name,
                            zone_id=zone.id if zone is not None else None,
                            zone_code=zone.code if zone is not None else None,
                        ),
                    )

                    self.connect(
                        movement_node_id,
                        warehouse_node_id,
                        label="Stored in warehouse",
                        source="record",
                        details=_details(
                            warehouse_id=warehouse.id,
                            storage_location_id=location.id,
                        ),
                    )

                stock_item = (
                    self.db.query(StockItem)
                    .filter(
                        StockItem.company_id == self.company_id,
                        StockItem.item_id == movement.item_id,
                        StockItem.storage_location_id == location_id,
                    )
                    .first()
                )

                if stock_item is not None:
                    stock_item_node_id = f"stock_item:{stock_item.id}"

                    self.node(
                        id=stock_item_node_id,
                        kind="stock_item",
                        state="current",
                        title=f"Stock item {stock_item.item_id}",
                        description=None,
                        source="record",
                        route="/warehouse/stock",
                        created_at=stock_item.created_at,
                        changed_at=stock_item.updated_at,
                        details=_details(
                            stock_item_id=stock_item.id,
                            item_id=stock_item.item_id,
                            storage_location_id=stock_item.storage_location_id,
                            quantity_on_hand=stock_item.quantity_on_hand,
                            quantity_reserved=stock_item.quantity_reserved,
                            quantity_available=stock_item.quantity_available,
                            unit_cost=stock_item.unit_cost,
                            unit_cost_base=stock_item.unit_cost_base,
                        ),
                    )

                    self.connect(
                        movement_node_id,
                        stock_item_node_id,
                        label="Updated stock balance",
                        source="record",
                        details=_details(stock_item_id=stock_item.id),
                    )


def build_business_flow(
    db: Session,
    company_id: int,
    root_type: str,
    root_id: int,
) -> BusinessFlowResponse:
    builder = BusinessFlowBuilder(db, company_id)

    if root_type == "mr":
        mr = builder.get_mr(root_id)
        builder.add_mr(mr)

        rfq = (
            db.query(RequestForQuotation)
            .filter(
                RequestForQuotation.company_id == company_id,
                RequestForQuotation.mr_id == mr.id,
            )
            .first()
        )

        if rfq is not None:
            builder.add_rfq(rfq, include_downstream=True)

        return builder.response(root_type, root_id)

    if root_type == "rfq":
        rfq = builder.get_rfq(root_id)

        if rfq.mr_id:
            mr = (
                db.query(MaterialRequisition)
                .filter(
                    MaterialRequisition.id == rfq.mr_id,
                    MaterialRequisition.company_id == company_id,
                )
                .first()
            )

            if mr is not None:
                builder.add_mr(mr)

        builder.add_rfq(rfq, include_downstream=True)
        return builder.response(root_type, root_id)

    if root_type == "po":
        po = builder.get_po(root_id)
        builder.add_po(po, include_upstream=True)
        return builder.response(root_type, root_id)

    if root_type == "grn":
        grn = builder.get_grn(root_id)
        builder.add_grn(grn, include_upstream=True)
        return builder.response(root_type, root_id)

    if root_type == "stock":
        movement = builder.get_stock_movement(root_id)
        builder.add_stock_movement(movement, include_upstream=True)
        return builder.response(root_type, root_id)

    raise BusinessFlowNotFound("unsupported_flow_root_type")
