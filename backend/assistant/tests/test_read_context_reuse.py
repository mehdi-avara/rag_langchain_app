import asyncio
from types import SimpleNamespace

import supplier_management.assistant_tools  # noqa: F401

from assistant import router as router_mod
from assistant import runner as runner_mod
from assistant.graph import build_assistant_graph
from assistant.registry import get_toolset
from assistant.tests.fakes import ALL_COMMERCE_PERMS, FakeDB, make_user


def test_load_latest_read_context_from_prior_run():
    db = FakeDB()
    user = make_user(ALL_COMMERCE_PERMS)

    context_state = {
        "selected_module": "supplier_management",
        "selected_task": "search_suppliers",
        "question": "Find ACME",
        "retrieved_items": [
            {
                "resource_type": "supplier",
                "citation_key": "supplier:5",
                "title": "ACME",
                "data": {"supplier_id": 5},
            }
        ],
        "summary": None,
        "citations": ["supplier:5"],
    }

    db.set_all(
        "AgentRun",
        [SimpleNamespace(state=context_state)],
    )

    result = runner_mod._load_latest_read_context(
        db,
        chat_id=1,
        user=user,
    )

    assert result["selected_module"] == "supplier_management"
    assert result["selected_task"] == "search_suppliers"
    assert result["retrieved_items"] == context_state["retrieved_items"]


def test_previous_result_followup_reuses_records_without_search(monkeypatch):
    async def fake_classify_module(**kwargs):
        return {
            "module": "supplier_management",
            "language": "en",
            "confidence": 0.99,
            "clarify_question": None,
        }

    async def fake_classify_task(**kwargs):
        return {
            "intent": "ask_suppliers",
            "language": "en",
            "confidence": 0.99,
            "slots": {"question": "Tell me more about the last result"},
            "clarify_question": None,
        }

    async def fail_if_searched(**kwargs):
        raise AssertionError("Database search should not run for a previous-result follow-up")

    monkeypatch.setattr(router_mod, "classify_module", fake_classify_module)
    monkeypatch.setattr(router_mod, "classify_task", fake_classify_task)

    toolset = get_toolset("supplier_management")
    monkeypatch.setattr(toolset, "handle_read", fail_if_searched)

    cached_items = [
        {
            "resource_type": "supplier",
            "source_type": "supplier_management",
            "citation_key": "supplier:5",
            "title": "ACME",
            "data": {
                "supplier_id": 5,
                "name": "ACME",
                "country": "UAE",
            },
        }
    ]

    result = asyncio.run(
        build_assistant_graph().ainvoke(
            {
                "user": make_user(ALL_COMMERCE_PERMS),
                "db": None,
                "question": "Tell me more about the last result",
                "history": [],
                "attachments": [],
                "slots": {},
                "step_count": 0,
                "active_read_context": {
                    "selected_module": "supplier_management",
                    "selected_task": "search_suppliers",
                    "retrieved_items": cached_items,
                    "summary": None,
                    "citations": ["supplier:5"],
                },
            }
        )
    )

    assert result["retrieved_items"] == cached_items
    assert result["citations"] == ["supplier:5"]
    assert result["tool_calls"][-1]["kind"] == "read_context_reuse"


def test_explicit_search_again_does_not_reuse_previous_records(monkeypatch):
    async def fake_classify_module(**kwargs):
        return {
            "module": "supplier_management",
            "language": "en",
            "confidence": 0.99,
            "clarify_question": None,
        }

    async def fake_classify_task(**kwargs):
        return {
            "intent": "search_suppliers",
            "language": "en",
            "confidence": 0.99,
            "slots": {"query": "ACME"},
            "clarify_question": None,
        }

    calls = {"count": 0}

    async def fake_search(**kwargs):
        calls["count"] += 1
        return {
            "retrieved_items": [],
            "summary": None,
            "answer": "",
            "citations": [],
        }

    monkeypatch.setattr(router_mod, "classify_module", fake_classify_module)
    monkeypatch.setattr(router_mod, "classify_task", fake_classify_task)

    toolset = get_toolset("supplier_management")
    monkeypatch.setattr(toolset, "handle_read", fake_search)

    asyncio.run(
        build_assistant_graph().ainvoke(
            {
                "user": make_user(ALL_COMMERCE_PERMS),
                "db": None,
                "question": "Search again for ACME",
                "history": [],
                "attachments": [],
                "slots": {},
                "step_count": 0,
                "active_read_context": {
                    "selected_module": "supplier_management",
                    "selected_task": "search_suppliers",
                    "retrieved_items": [{"citation_key": "supplier:5"}],
                    "summary": None,
                    "citations": ["supplier:5"],
                },
            }
        )
    )

    assert calls["count"] == 1
