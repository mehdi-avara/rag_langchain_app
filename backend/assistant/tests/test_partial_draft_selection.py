import asyncio
from types import SimpleNamespace

import requisition_management.assistant_tools  # noqa: F401

from assistant import router as router_mod
from assistant import runner as runner_mod
from assistant.graph import (
    _localized_clarify_question,
    _matching_partial_draft,
    build_assistant_graph,
)
from assistant.registry import DraftData
from assistant.tests.fakes import (
    ALL_COMMERCE_PERMS,
    FakeDB,
    make_user,
)


def _run(state):
    return asyncio.run(build_assistant_graph().ainvoke(state))


def test_loads_latest_active_partial_for_each_module_and_action():
    db = FakeDB()
    user = make_user(ALL_COMMERCE_PERMS)

    po_partial = {
        "target_module": "purchase_management",
        "target_action": "create_purchase_order",
        "payload": {"title": "Pump PO"},
    }
    rfq_partial = {
        "target_module": "rfq_management",
        "target_action": "create_rfq",
        "payload": {"title": "Pump RFQ"},
    }
    mr_partial = {
        "target_module": "requisition_management",
        "target_action": "create_material_requisition",
        "payload": {"priority": "normal"},
    }
    completed_rfq = {
        "target_module": "rfq_management",
        "target_action": "create_rfq",
        "payload": {
            "title": "Pump RFQ",
            "deadline_date": "2026-08-10",
            "mr_id": 4,
        },
        "commit_target": {
            "method": "POST",
            "endpoint": "/rfqs",
            "permission": "rfq_management:create",
        },
        "validation": {"valid": True},
    }

    db.set_all(
        "AgentRun",
        [
            SimpleNamespace(state={"partial_draft": po_partial}),
            SimpleNamespace(state={"pending_draft": completed_rfq}),
            SimpleNamespace(state={"partial_draft": rfq_partial}),
            SimpleNamespace(state={"partial_draft": mr_partial}),
        ],
    )

    result = runner_mod._load_active_partial_drafts(
        db,
        chat_id=1,
        user=user,
    )

    assert result == [po_partial, mr_partial]


def test_matching_partial_requires_module_and_action():
    state = {
        "active_partial_drafts": [
            {
                "target_module": "module_a",
                "target_action": "create_record",
                "payload": {"value": "wrong module"},
            },
            {
                "target_module": "module_b",
                "target_action": "create_record",
                "payload": {"value": "correct"},
            },
        ]
    }
    spec = SimpleNamespace(
        module="module_b",
        target_action="create_record",
    )

    result = _matching_partial_draft(state, spec)

    assert result["payload"]["value"] == "correct"


def test_graph_merges_matching_mr_partial_not_latest_po_partial(
    monkeypatch,
):
    async def fake_classify_module(**kwargs):
        return {
            "module": "requisition_management",
            "language": "en",
            "confidence": 0.99,
            "clarify_question": None,
        }

    async def fake_classify_task(**kwargs):
        return {
            "intent": "add_material_requisition",
            "language": "en",
            "confidence": 0.99,
            "slots": {
                "needed_by_date": "2026-08-01",
                "reason": "Pump repair",
            },
            "clarify_question": None,
        }

    monkeypatch.setattr(
        router_mod,
        "classify_module",
        fake_classify_module,
    )
    monkeypatch.setattr(
        router_mod,
        "classify_task",
        fake_classify_task,
    )

    result = _run(
        {
            "user": make_user(ALL_COMMERCE_PERMS),
            "db": None,
            "question": "Complete the MR for pump repair.",
            "history": [],
            "attachments": [],
            "slots": {},
            "step_count": 0,
            "active_partial_drafts": [
                {
                    "target_module": "purchase_management",
                    "target_action": "create_purchase_order",
                    "payload": {"title": "Pump PO"},
                },
                {
                    "target_module": "requisition_management",
                    "target_action": "create_material_requisition",
                    "payload": {
                        "department_id": 7,
                        "priority": "normal",
                    },
                },
            ],
        }
    )

    draft = result["pending_draft"]

    assert draft["target_module"] == "requisition_management"
    assert draft["target_action"] == "create_material_requisition"
    assert draft["payload"]["department_id"] == 7
    assert draft["payload"]["priority"] == "normal"
    assert draft["payload"]["needed_by_date"] == "2026-08-01"
    assert draft["payload"]["reason"] == "Pump repair"
    assert "title" not in draft["payload"]


def test_persian_partial_draft_question_is_localized():
    draft_data = DraftData(
        target_module="requisition_management",
        target_action="create_material_requisition",
        payload={"priority": "normal"},
        commit_target={},
        validation={
            "valid": False,
            "missing": ["needed_by_date", "reason"],
            "errors": {},
        },
        valid=False,
        clarify_question="I still need: needed_by_date, reason.",
    )

    question = _localized_clarify_question(
        language="fa",
        draft_data=draft_data,
    )

    assert "تاریخ موردنیاز" in question
    assert "دلیل درخواست" in question
    assert "I still need" not in question
