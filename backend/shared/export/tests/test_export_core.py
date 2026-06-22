from __future__ import annotations

from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from shared.export import services
from shared.export.datasets import (
    ExportValidationError,
    normalize_filters,
    resolve_columns,
)
from shared.export.renderers import render_export
from shared.export.schemas import ExportRequest


def test_csv_export_uses_utf8_bom_and_requested_columns():
    content, content_type, extension = render_export(
        export_format="csv",
        title="Suppliers",
        columns=["code", "name"],
        labels={"code": "Code", "name": "Name"},
        rows=[{"code": "SUP-001", "name": "Acme"}],
        filters={},
    )

    assert content.startswith(b"\xef\xbb\xbf")
    assert b"Code,Name" in content
    assert content_type.startswith("text/csv")
    assert extension == "csv"


def test_xlsx_export_freezes_header_and_keeps_values():
    content, content_type, extension = render_export(
        export_format="xlsx",
        title="Stock",
        columns=["item_code", "inventory_value_base"],
        labels={
            "item_code": "Item Code",
            "inventory_value_base": "Inventory Value Base",
        },
        rows=[
            {
                "item_code": "BOLT-M12",
                "inventory_value_base": 1250.5,
            }
        ],
        filters={},
    )

    workbook = load_workbook(BytesIO(content))
    worksheet = workbook.active

    assert worksheet.freeze_panes == "A2"
    assert worksheet["A1"].value == "Item Code"
    assert worksheet["B2"].value == 1250.5
    assert content_type.startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert extension == "xlsx"


def test_pdf_export_creates_pdf_document():
    content, content_type, extension = render_export(
        export_format="pdf",
        title="Suppliers",
        columns=["code", "name"],
        labels={"code": "Code", "name": "Name"},
        rows=[{"code": "SUP-001", "name": "Acme"}],
        filters={"status": "active"},
    )

    assert content.startswith(b"%PDF")
    assert content_type == "application/pdf"
    assert extension == "pdf"


def test_export_columns_and_filters_are_validated():
    columns = resolve_columns(
        "supplier_management",
        "suppliers",
        ["name", "code"],
    )
    filters = normalize_filters(
        "supplier_management",
        "suppliers",
        {"status": "active", "limit": 20},
    )

    assert columns == ["name", "code"]
    assert filters["status"] == "active"
    assert filters["limit"] == 20

    with pytest.raises(ExportValidationError):
        resolve_columns(
            "supplier_management",
            "suppliers",
            ["unknown_column"],
        )

    with pytest.raises(ExportValidationError):
        normalize_filters(
            "supplier_management",
            "suppliers",
            {"unknown_filter": "value"},
        )

    with pytest.raises(ExportValidationError):
        normalize_filters(
            "requisition_management",
            "requisitions",
            {"query": "urgent", "status": "approved"},
        )

    with pytest.raises(ExportValidationError):
        normalize_filters(
            "goods_receipt_management",
            "goods_receipts",
            {"query": "delivery", "receipt_date_from": "2026-01-01"},
        )


def test_queue_export_creates_audit_task_and_dispatches_celery(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.added = []
            self.commits = 0

        def add(self, value):
            self.added.append(value)

        def flush(self):
            for value in self.added:
                if value.__class__.__name__ == "ExportAuditLog" and value.id is None:
                    value.id = 17

        def commit(self):
            self.flush()
            self.commits += 1

        def rollback(self):
            return None

    db = FakeDb()
    user = SimpleNamespace(id=8, company_id=4)
    sent = {}

    def fake_send_task(name, args):
        sent["name"] = name
        sent["args"] = args
        return SimpleNamespace(id="celery-export-smoke")

    monkeypatch.setattr(
        services.celery_app,
        "send_task",
        fake_send_task,
    )

    result = services.queue_export(
        db=db,
        current_user=user,
        module="supplier_management",
        entity="suppliers",
        payload=ExportRequest(format="csv"),
    )

    assert result.task_type == "export:supplier_management:suppliers"
    assert result.audit_id == 17
    assert sent["name"] == "shared.export.tasks.generate_export"
    assert sent["args"][1:] == [17, 8]
    assert db.commits == 2


def test_query_cannot_mix_with_filters_that_search_ignores():
    with pytest.raises(ExportValidationError):
        normalize_filters(
            "requisition_management",
            "requisitions",
            {"query": "urgent", "status": "approved"},
        )

    with pytest.raises(ExportValidationError):
        normalize_filters(
            "rfq_management",
            "rfqs",
            {"query": "pump", "mr_id": 7},
        )

    with pytest.raises(ExportValidationError):
        normalize_filters(
            "goods_receipt_management",
            "goods_receipts",
            {"query": "delivery", "receipt_date_from": "2026-01-01"},
        )


def test_export_task_declares_retry_policy():
    from shared.export.tasks import generate_export_task

    assert generate_export_task.max_retries == 3
    assert generate_export_task.default_retry_delay == 60
