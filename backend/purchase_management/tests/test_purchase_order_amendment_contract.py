from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from purchase_management.models import (
    PurchaseAmendmentStatus,
    PurchaseOrder,
    PurchaseOrderAmendment,
)
from purchase_management.permissions import (
    PERMISSIONS,
)
from purchase_management.schemas import (
    PurchaseOrderAmendmentCreate,
    PurchaseOrderAmendmentDecision,
    PurchaseOrderApproval,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)


def test_amendment_model_contract():
    assert (
        PurchaseOrderAmendment.__tablename__
        == "purchase_order_amendments"
    )

    columns = set(
        PurchaseOrderAmendment
        .__table__
        .columns
        .keys()
    )

    assert columns == {
        "id",
        "company_id",
        "purchase_order_id",
        "amendment_number",
        "status",
        "reason",
        "before_snapshot",
        "proposed_snapshot",
        "submission_note",
        "decision_note",
        "created_by_user_id",
        "submitted_by_user_id",
        "decided_by_user_id",
        "created_at",
        "submitted_at",
        "decided_at",
        "updated_at",
    }

    assert {
        item.value
        for item in PurchaseAmendmentStatus
    } == {
        "draft",
        "pending",
        "approved",
        "rejected",
    }


def test_purchase_order_active_amendment_properties():
    purchase_order = PurchaseOrder()

    draft = PurchaseOrderAmendment(
        id=12,
        amendment_number=2,
        status=PurchaseAmendmentStatus.DRAFT.value,
        reason="Change supplier",
        before_snapshot={},
    )

    purchase_order.amendments = [draft]

    assert purchase_order.active_amendment is draft
    assert purchase_order.active_amendment_id == 12
    assert (
        purchase_order.active_amendment_status
        == "draft"
    )
    assert purchase_order.amendment_count == 1

    draft.status = (
        PurchaseAmendmentStatus.APPROVED.value
    )

    assert purchase_order.active_amendment is None
    assert purchase_order.active_amendment_id is None
    assert (
        purchase_order.active_amendment_status
        is None
    )


def test_purchase_order_update_cannot_set_status():
    assert (
        "status"
        not in PurchaseOrderUpdate.model_fields
    )


def test_purchase_order_approval_actions_are_decisions_only():
    annotation = (
        PurchaseOrderApproval
        .model_fields["action"]
        .annotation
    )

    assert set(get_args(annotation)) == {
        "approve",
        "reject",
    }


def test_rejection_requires_note():
    with pytest.raises(ValidationError):
        PurchaseOrderApproval(
            action="reject",
        )

    with pytest.raises(ValidationError):
        PurchaseOrderAmendmentDecision(
            action="reject",
            note=" ",
        )


def test_amendment_reason_is_trimmed_and_required():
    payload = PurchaseOrderAmendmentCreate(
        reason="  Change commercial terms  ",
    )

    assert payload.reason == (
        "Change commercial terms"
    )

    with pytest.raises(ValidationError):
        PurchaseOrderAmendmentCreate(
            reason=" ",
        )


def test_purchase_order_read_exposes_amendment_state():
    assert {
        "active_amendment_id",
        "active_amendment_status",
        "amendment_count",
    }.issubset(
        PurchaseOrderRead.model_fields
    )


def test_purchase_amendment_permissions_registered():
    names = {
        item[0]
        for item in PERMISSIONS
    }

    assert (
        "purchase_management:orders:submit"
        in names
    )
    assert (
        "purchase_management:orders:amend"
        in names
    )


def test_migration_h_contract():
    path = Path(
        "alembic/versions/"
        "b1c2d3e4f5a6_add_"
        "purchase_order_amendments.py"
    )

    content = path.read_text(
        encoding="utf-8"
    )

    required = (
        'revision: str = "b1c2d3e4f5a6"',
        '"a0b1c2d3e4f5"',
        '"purchase_order_amendments"',
        '"before_snapshot"',
        '"proposed_snapshot"',
        '"uq_purchase_order_amendments_"',
        '"active_order"',
        "purchase_management:orders:submit",
        "purchase_management:orders:amend",
        "ON CONFLICT DO NOTHING",
    )

    for value in required:
        assert value in content



def test_amendment_openapi_contract():
    from api import app

    paths = app.openapi()["paths"]

    assert (
        "/purchase/orders/{po_id}/submit"
        in paths
    )
    assert (
        "/purchase/orders/{po_id}/amendments"
        in paths
    )
    assert (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}"
        in paths
    )
    assert (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}/submit"
        in paths
    )
    assert (
        "/purchase/orders/{po_id}/amendments/"
        "{amendment_id}/approval"
        in paths
    )

    assert (
        "post"
        in paths[
            "/purchase/orders/{po_id}/submit"
        ]
    )
    assert (
        "patch"
        in paths[
            "/purchase/orders/{po_id}/amendments/"
            "{amendment_id}/approval"
        ]
    )



def test_purchase_order_read_schema_keeps_lines():
    assert (
        "lines"
        in PurchaseOrderRead.model_fields
    )



def test_purchase_order_row_locks_target_base_table():
    paths = (
        Path(
            "purchase_management/"
            "amendment_service.py"
        ),
        Path(
            "purchase_management/"
            "services.py"
        ),
    )

    lock_count = 0

    for path in paths:
        lines = path.read_text(
            encoding="utf-8"
        ).splitlines()

        inside_purchase_order_query = False

        for line in lines:
            if "db.query(PurchaseOrder)" in line:
                inside_purchase_order_query = True

            if (
                inside_purchase_order_query
                and ".with_for_update" in line
            ):
                lock_count += 1

                assert (
                    ".with_for_update("
                    "of=PurchaseOrder"
                    ")"
                    in line
                )

            if (
                inside_purchase_order_query
                and any(
                    terminal in line
                    for terminal in (
                        ".first()",
                        ".one()",
                        ".one_or_none()",
                        ".scalar()",
                        ".all()",
                    )
                )
            ):
                inside_purchase_order_query = False

    assert lock_count >= 1



def test_loaded_allocations_are_deleted_through_orm_ownership():
    services = Path(
        "purchase_management/services.py"
    ).read_text(
        encoding="utf-8"
    )

    update_start = services.index(
        "def update_purchase_order_line("
    )
    update_end = services.index(
        "def delete_purchase_order_line(",
        update_start,
    )
    update_source = services[
        update_start:update_end
    ]

    delete_start = update_end
    delete_end = services.index(
        "def cancel_purchase_order(",
        delete_start,
    )
    delete_source = services[
        delete_start:delete_end
    ]

    assert (
        "synchronize_session=False"
        not in update_source
    )
    assert (
        "synchronize_session=False"
        not in delete_source
    )
    assert (
        "for allocation in list("
        in update_source
    )
    assert "db.delete(line)" in delete_source


def test_snapshot_restore_does_not_double_delete_removed_line_allocations():
    source = Path(
        "purchase_management/"
        "amendment_service.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def restore_purchase_order_"
        "commercial_snapshot("
    )
    end = source.index(
        "def get_active_purchase_order_amendment(",
        start,
    )
    restore_source = source[start:end]

    assert (
        "allocation.purchase_order_line_id"
        in restore_source
    )
    assert (
        "in snapshot_lines"
        in restore_source
    )
