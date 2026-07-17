from assistant.tests.fakes import ALL_COMMERCE_PERMS, make_user
from requisition_management.assistant_tools import RequisitionAssistantToolSet
from requisition_management.models import MaterialRequisition
from requisition_management.schemas import MaterialRequisitionCreate


def test_material_requisition_create_allows_missing_needed_date():
    payload = MaterialRequisitionCreate(reason="Pump repair")

    assert payload.needed_by_date is None
    assert payload.reason == "Pump repair"


def test_material_requisition_database_column_is_nullable():
    assert MaterialRequisition.__table__.c.needed_by_date.nullable is True


def test_assistant_mr_draft_does_not_require_needed_date():
    toolset = RequisitionAssistantToolSet()

    draft = toolset.build_draft(
        intent="add_material_requisition",
        db=None,
        user=make_user(ALL_COMMERCE_PERMS),
        slots={"reason": "Pump repair"},
        attachments=[],
    )

    assert draft.valid is True
    assert draft.payload["reason"] == "Pump repair"
    assert "needed_by_date" not in draft.payload
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/requisitions",
        "permission": "requisition_management:create",
    }
