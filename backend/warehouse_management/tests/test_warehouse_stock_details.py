from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import material_management.services as material_services
from warehouse_management.schemas import StockItemSearchRead
import warehouse_management.services as warehouse_services


class QueryStub:
    def __init__(self, rows):
        self.rows = rows
        self.offset_value = None
        self.limit_value = None

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows


class DummyDB:
    def __init__(self, rows):
        self.query_stub = QueryStub(rows)

    def query(self, *models):
        return self.query_stub


def test_list_stock_item_details_returns_item_and_location_metadata(monkeypatch):
    stock_item = SimpleNamespace(
        id=11,
        company_id=3,
        item_id=7,
        storage_location_id=9,
        quantity_on_hand=Decimal("3.0000"),
        quantity_reserved=Decimal("1.0000"),
        quantity_available=Decimal("2.0000"),
        min_level=Decimal("1.0000"),
        max_level=Decimal("10.0000"),
        reorder_point=Decimal("2.0000"),
        unit_cost=Decimal("12.50"),
        unit_cost_currency_id=1,
        unit_cost_base=Decimal("12.50"),
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        updated_at=datetime(2026, 7, 5, 10, 5, 0),
    )
    location = SimpleNamespace(id=9, code="A-01", name="Primary Location")
    zone = SimpleNamespace(id=4, code="MAIN", name="Main Zone")
    warehouse = SimpleNamespace(id=2, code="WH-01", name="Main Warehouse")
    db = DummyDB([(stock_item, location, zone, warehouse)])
    current_user = SimpleNamespace(company_id=3)

    def fake_get_item_references(db, current_user, item_ids):
        assert item_ids == [7]
        return {
            7: {
                "id": 7,
                "item_code": "MAT-007",
                "name": "Steel Bolt",
                "unit_code": "EA",
            }
        }

    monkeypatch.setattr(
        material_services,
        "get_item_references",
        fake_get_item_references,
    )

    result = warehouse_services.list_stock_item_details(
        db=db,
        current_user=current_user,
        limit=50,
        offset=0,
    )

    assert db.query_stub.offset_value == 0
    assert db.query_stub.limit_value == 50
    assert result[0]["item_code"] == "MAT-007"
    assert result[0]["item_name"] == "Steel Bolt"
    assert result[0]["unit_code"] == "EA"
    assert result[0]["warehouse_name"] == "Main Warehouse"
    assert result[0]["storage_location_name"] == "Primary Location"
    assert result[0]["inventory_value_base"] == Decimal("37.500000")

    parsed = StockItemSearchRead.model_validate(result[0])

    assert parsed.item_id == 7
    assert parsed.item_name == "Steel Bolt"
