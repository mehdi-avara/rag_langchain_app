from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from api import app
from goods_receipt_management.permissions import PERMISSIONS as GRN_PERMISSIONS
from goods_receipt_management.search import service as grn_search
from requisition_management.permissions import PERMISSIONS as REQUISITION_PERMISSIONS
from requisition_management.search import service as requisition_search
from rfq_management.permissions import PERMISSIONS as RFQ_PERMISSIONS
from rfq_management.search import service as rfq_search
from warehouse_management.permissions import PERMISSIONS as WAREHOUSE_PERMISSIONS
from warehouse_management.search import service as warehouse_search


def _openapi_paths() -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]

    return {
        (path, method.upper())
        for path, operations in paths.items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }


def test_phase1_search_and_ask_routes_are_registered():
    paths = _openapi_paths()

    assert ("/requisitions/search", "POST") in paths
    assert ("/requisitions/ask", "POST") in paths
    assert ("/rfqs/search", "POST") in paths
    assert ("/rfqs/ask", "POST") in paths
    assert ("/goods-receipts/search", "POST") in paths
    assert ("/goods-receipts/ask", "POST") in paths
    assert ("/warehouse/search", "POST") in paths
    assert ("/warehouse/ask", "POST") in paths


def test_phase1_ask_permissions_are_declared():
    assert "requisition_management:ask" in {
        row[0] for row in REQUISITION_PERMISSIONS
    }
    assert "rfq_management:ask" in {
        row[0] for row in RFQ_PERMISSIONS
    }
    assert "goods_receipt_management:ask" in {
        row[0] for row in GRN_PERMISSIONS
    }
    assert "warehouse_management:ask" in {
        row[0] for row in WAREHOUSE_PERMISSIONS
    }


def test_requisition_vector_search_uses_item_bridge(monkeypatch):
    record = SimpleNamespace(
        id=1,
        company_id=1,
        mr_number="MR-2026-0001",
        status="approved",
        priority="normal",
        reason="Pump seal replacement",
        needed_by_date=date(2026, 6, 30),
        items=[SimpleNamespace(item_id=11, item_code="SEAL-01")],
    )

    monkeypatch.setattr(
        requisition_search,
        "search_item_hits",
        lambda **kwargs: [
            SimpleNamespace(item_id=11, match_source="semantic")
        ],
    )
    monkeypatch.setattr(
        requisition_search,
        "search_requisitions_by_item_ids",
        lambda **kwargs: [record],
    )

    hits = requisition_search.search_requisition_hits(
        db=None,
        current_user=SimpleNamespace(),
        query_text="pump seal",
        mode="vector",
    )

    assert hits[0].requisition_id == 1
    assert hits[0].match_source == "semantic_item"


def test_rfq_vector_search_uses_item_bridge(monkeypatch):
    record = SimpleNamespace(
        id=2,
        company_id=1,
        rfq_number="RFQ-2026-0001",
        status="sent",
        title="Pump spares",
        description=None,
        deadline_date=date(2026, 7, 1),
        items=[SimpleNamespace(item_id=12, item_code="PUMP-01")],
    )

    monkeypatch.setattr(
        rfq_search,
        "search_item_hits",
        lambda **kwargs: [
            SimpleNamespace(item_id=12, match_source="semantic")
        ],
    )
    monkeypatch.setattr(
        rfq_search,
        "search_rfqs_by_item_ids",
        lambda **kwargs: [record],
    )

    hits = rfq_search.search_rfq_hits(
        db=None,
        current_user=SimpleNamespace(),
        query_text="pump spare",
        mode="vector",
    )

    assert hits[0].rfq_id == 2
    assert hits[0].match_source == "semantic_item"


def test_grn_vector_search_uses_item_bridge(monkeypatch):
    record = SimpleNamespace(
        id=3,
        company_id=1,
        grn_number="GRN-2026-0001",
        status="posted",
        receipt_date=date(2026, 6, 23),
        delivery_note_number="DN-1",
        warehouse_id=1,
        items=[SimpleNamespace(item_id=13, item_code="VALVE-01")],
    )

    monkeypatch.setattr(
        grn_search,
        "search_item_hits",
        lambda **kwargs: [
            SimpleNamespace(item_id=13, match_source="semantic")
        ],
    )
    monkeypatch.setattr(
        grn_search,
        "search_goods_receipts_by_item_ids",
        lambda **kwargs: [record],
    )

    hits = grn_search.search_goods_receipt_hits(
        db=None,
        current_user=SimpleNamespace(),
        query_text="valve",
        mode="vector",
    )

    assert hits[0].goods_receipt_id == 3
    assert hits[0].match_source == "semantic_item"


def test_warehouse_vector_search_uses_item_bridge(monkeypatch):
    row = {
        "id": 4,
        "company_id": 1,
        "item_id": 14,
        "item_code": "BOLT-01",
        "item_name": "Bolt",
        "unit_code": "PCS",
        "warehouse_id": 1,
        "warehouse_code": "MAIN",
        "warehouse_name": "Main",
        "storage_location_id": 1,
        "storage_location_code": "A-01",
        "storage_location_name": "A-01",
        "quantity_on_hand": Decimal("10"),
        "quantity_reserved": Decimal("2"),
        "quantity_available": Decimal("8"),
        "unit_cost": Decimal("2"),
        "unit_cost_base": Decimal("2"),
        "inventory_value_base": Decimal("20"),
        "created_at": datetime(2026, 6, 23),
        "updated_at": datetime(2026, 6, 23),
    }

    monkeypatch.setattr(
        warehouse_search,
        "search_item_hits",
        lambda **kwargs: [
            SimpleNamespace(item_id=14, match_source="semantic")
        ],
    )
    monkeypatch.setattr(
        warehouse_search,
        "search_stock_by_item_ids",
        lambda **kwargs: [row],
    )

    hits = warehouse_search.search_warehouse_hits(
        db=None,
        current_user=SimpleNamespace(),
        query_text="bolt",
        mode="vector",
    )

    assert hits[0].stock_item_id == 4
    assert hits[0].match_source == "semantic_item"
