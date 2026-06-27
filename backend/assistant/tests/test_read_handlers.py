"""PROMPT §10.1 — read handlers (search / summarize / ask) with services mocked + RBAC re-checked."""

import asyncio

import pytest

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, make_user

import financial_management.assistant_tools as ft
from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import PERMISSION_DENIED

toolset = ft.FinancialAssistantToolSet()


class _FakeHit:
    def __init__(self, receipt_id):
        self.receipt_id = receipt_id

    def model_dump(self, mode=None):
        return {"receipt_id": self.receipt_id, "amount": "100", "direction": "output"}


class _FakeSummary:
    def model_dump(self, mode=None):
        return {"base_currency": "IRT", "net_base": "500", "receipt_count": 3, "by_currency": []}


class _FakeAskResponse:
    answer = "The last invoice from ACME was about a pump. [receipt:7]"
    used_receipt_ids = [7]
    references = [_FakeHit(7)]


def test_search_handler_builds_items(monkeypatch):
    monkeypatch.setattr(ft, "search_receipt_hits", lambda **kw: [_FakeHit(1), _FakeHit(2)])
    user = make_user(ALL_FINANCIAL_PERMS)
    out = asyncio.run(toolset.handle_read(intent="search_receipts", db=None, user=user, slots={"query": "pump"}))
    assert [i["citation_key"] for i in out["retrieved_items"]] == ["receipt:1", "receipt:2"]
    assert out["summary"] is None


def test_summarize_handler_returns_summary(monkeypatch):
    monkeypatch.setattr(ft, "summarize_receipts", lambda *a, **k: _FakeSummary())
    user = make_user(ALL_FINANCIAL_PERMS)
    out = asyncio.run(toolset.handle_read(intent="summarize_finance", db=None, user=user, slots={}))
    assert out["summary"]["receipt_count"] == 3
    assert out["retrieved_items"] == []


def test_ask_handler_returns_answer_and_citations(monkeypatch):
    async def _fake_answer(*a, **k):
        return _FakeAskResponse()

    monkeypatch.setattr(ft, "answer_receipts_question", _fake_answer)
    user = make_user(ALL_FINANCIAL_PERMS)
    out = asyncio.run(toolset.handle_read(intent="ask_finance", db=None, user=user, slots={"question": "last ACME invoice?"}))
    assert "pump" in out["answer"]
    assert out["citations"] == ["receipt:7"]


def test_search_rechecks_permission():
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:receipts:search"]
    user = make_user(perms)
    with pytest.raises(AppException) as exc:
        asyncio.run(toolset.handle_read(intent="search_receipts", db=None, user=user, slots={"query": "x"}))
    assert exc.value.code == PERMISSION_DENIED
