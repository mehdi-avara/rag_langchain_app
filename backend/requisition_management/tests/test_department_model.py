from requisition_management.models import MaterialRequisition
from requisition_management.schemas import MaterialRequisitionRead


def test_material_requisition_department_has_organization_fk():
    department_column = (
        MaterialRequisition.__table__.c.department_id
    )

    targets = {
        foreign_key.target_fullname
        for foreign_key in department_column.foreign_keys
    }

    assert targets == {
        "organization_departments.id",
    }


def test_material_requisition_preserves_legacy_department():
    column = (
        MaterialRequisition.__table__.c.legacy_department_id
    )

    assert column.nullable is True
    assert "legacy_department_id" in MaterialRequisitionRead.model_fields
