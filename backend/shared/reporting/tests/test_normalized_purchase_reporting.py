import inspect
from decimal import Decimal
from types import SimpleNamespace

import shared.reporting.services as reporting


USER = SimpleNamespace(company_id=1)


def test_reporting_has_no_legacy_phase_item_queries():
    source = inspect.getsource(reporting)

    assert "purchase_phase_items" not in source
    assert source.count(
        "FROM purchase_order_lines line"
    ) >= 3
    assert "purchase_phase_allocations" in source
    assert "goods_receipt_items" in source
    assert "receipt_note.status = 'posted'" in source


def test_variance_report_returns_normalized_totals(
    monkeypatch,
):
    captured_queries = []

    monkeypatch.setattr(
        reporting,
        "_currency_context",
        lambda db, company_id, currency_id: (
            1,
            "USD",
        ),
    )

    def fake_rows(db, query, params):
        captured_queries.append(query)

        return [
            {
                "label": "PO-2026-0001",
                "ordered_quantity": Decimal("5"),
                "received_quantity": Decimal("3"),
            }
        ]

    monkeypatch.setattr(
        reporting,
        "_rows",
        fake_rows,
    )

    result = reporting.purchase_report(
        db=None,
        current_user=USER,
        name="grn-vs-po-variance",
        group_by="purchase_order",
    )

    assert result["series"][0]["data"] == [
        Decimal("5")
    ]
    assert result["series"][1]["data"] == [
        Decimal("3")
    ]
    assert result["series"][2]["data"] == [
        Decimal("2")
    ]

    assert len(captured_queries) == 1

    query = captured_queries[0]

    assert "purchase_order_lines" in query
    assert "purchase_phase_allocations" in query
    assert "goods_receipt_items" in query
    assert "goods_receipt_notes" in query
    assert "receipt_note.status = 'posted'" in query
    assert "purchase_phase_items" not in query
