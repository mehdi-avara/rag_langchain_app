from business_management.permissions import PERMISSIONS
from business_management.schemas import (
    BusinessFlowConnection,
    BusinessFlowNode,
    BusinessFlowResponse,
    BusinessFlowRoot,
    BusinessFlowTimelineEvent,
)


def test_business_flow_response_shape_supports_frontend_contract():
    response = BusinessFlowResponse(
        root=BusinessFlowRoot(type="po", id=7),
        audit_coverage={
            "mr": "actual",
            "rfq": "partial",
            "quotation": "partial",
            "po": "inferred",
            "grn": "partial",
            "stock_movement": "actual",
        },
        nodes=[
            BusinessFlowNode(
                id="skipped:rfq:po:7",
                kind="skipped",
                state="skipped",
                title="RFQ skipped",
                description="This purchase order was created manually without an RFQ.",
                source="record",
                is_inferred=False,
            ),
            BusinessFlowNode(
                id="waiting:stock:grn:4",
                kind="blocked",
                state="waiting",
                title="Warehouse movement pending",
                description="GRN is posted, but no warehouse stock movement was found yet. Celery or backfill may still be pending.",
                source="record",
                is_inferred=False,
            ),
        ],
        connections=[
            BusinessFlowConnection(
                id="connection:skipped:rfq:po:7:po:7",
                from_node_id="skipped:rfq:po:7",
                to_node_id="po:7",
                label="Manual purchase order",
                source="record",
            )
        ],
        timeline=[
            BusinessFlowTimelineEvent(
                id="timeline:mr_status:1:2",
                kind="mr_status",
                state="approved",
                title="MR status changed to approved",
                source="audit",
                entity_type="mr",
                entity_id=1,
                actor_user_id=4,
                from_status="submitted",
                to_status="approved",
            )
        ],
    )

    assert response.nodes[0].id == "skipped:rfq:po:7"
    assert response.nodes[1].kind == "blocked"
    assert response.timeline[0].source == "audit"


def test_business_flow_permission_is_declared():
    names = {item[0] for item in PERMISSIONS}
    assert "business_management:flow:read" in names
