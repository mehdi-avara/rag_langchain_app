from supplier_management.models import Supplier

from purchase_management.models import PurchaseOrder
from purchase_management.schemas import (
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)


def test_purchase_order_supplier_is_normalized():
    columns = set(
        PurchaseOrder.__table__.columns.keys()
    )

    assert "supplier_id" in columns
    assert "supplier_name" not in columns

    supplier_column = (
        PurchaseOrder.__table__.columns[
            "supplier_id"
        ]
    )

    assert supplier_column.nullable is False

    foreign_keys = list(
        supplier_column.foreign_keys
    )

    assert len(foreign_keys) == 1
    assert foreign_keys[0].ondelete == "RESTRICT"


def test_purchase_order_supplier_name_is_derived():
    supplier = Supplier(
        id=9,
        company_id=1,
        code="SUP-0009",
        name="Vendor A",
        supplier_type="local",
        status="approved",
    )

    purchase_order = PurchaseOrder(
        company_id=1,
        reference_number="PO-TEST-1",
        supplier_id=9,
        supplier=supplier,
    )

    assert purchase_order.supplier_name == "Vendor A"


def test_purchase_order_contract_uses_supplier_id_only():
    update_fields = set(
        PurchaseOrderUpdate.model_fields
    )
    read_fields = set(
        PurchaseOrderRead.model_fields
    )

    assert "supplier_id" in update_fields
    assert "supplier_name" not in update_fields

    assert "supplier_id" in read_fields
    assert "supplier_name" in read_fields

    assert (
        PurchaseOrderRead.model_fields[
            "supplier_id"
        ].annotation
        is int
    )
