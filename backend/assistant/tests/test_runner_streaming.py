"""PROMPT §8.1 (history), §8.2 (streaming), §10.5/§10.7/§10.8.

The runner lazily imports ``routs.chat``; we inject a fake module so the test
runs without the full chat stack, and drive everything else with FakeDB + mocks.
"""

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, FakeDB, make_user

import financial_management.assistant_tools  # noqa: F401


# --- install a fake routs.chat before importing the runner ---------------------
_MESSAGES: list = []


def _install_fake_routs_chat(monkeypatch):
    _MESSAGES.clear()
    mod = ModuleType("routs.chat")

    def get_or_create_chat(db, *, chat_id, user):
        return SimpleNamespace(id=chat_id or 1), False

    def add_message(db, *, chat_id, role, content, citations=None, retrieved_chunks=None, draft_id=None):
        msg = SimpleNamespace(
            chat_id=chat_id, role=role, content=content,
            citations=citations, retrieved_chunks=retrieved_chunks, draft_id=draft_id,
        )
        _MESSAGES.append(msg)
        return msg

    mod.get_or_create_chat = get_or_create_chat
    mod.add_message = add_message
    monkeypatch.setitem(sys.modules, "routs.chat", mod)

from assistant import router as router_mod  # noqa: E402
from assistant import registry  # noqa: E402
from assistant import runner as runner_mod  # noqa: E402
from assistant import intake as intake_mod  # noqa: E402
from assistant.models import AgentRun, AgentRunStatus, Draft, DraftStatus  # noqa: E402
from assistant.schemas import AssistantChatRequest  # noqa: E402


def _parse_events(chunks):
    events = []
    for chunk in chunks:
        ev, data = None, None
        for line in chunk.strip().splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if ev:
            events.append((ev, data))
    return events


def _collect(db, user, request, monkeypatch, *, intent, slots=None, clarify=None):
    _install_fake_routs_chat(monkeypatch)
    db.set_all("AgentRun", [])

    spec = registry.find_intent(user, intent)
    selected_module = spec.module if spec and spec.module else ("clarify" if intent == "clarify" else "general")

    async def fake_classify_module(**kwargs):
        return {
            "module": selected_module, "language": "en", "confidence": 0.9,
            "clarify_question": clarify,
        }

    async def fake_classify_task(**kwargs):
        return {
            "intent": intent, "language": "en", "confidence": 0.9,
            "slots": slots or {}, "clarify_question": clarify,
        }

    monkeypatch.setattr(router_mod, "classify_module", fake_classify_module)
    monkeypatch.setattr(router_mod, "classify_task", fake_classify_task)
    # Avoid instantiating a live model client in the resolver.
    monkeypatch.setattr(
        intake_mod,
        "resolve_chat_model",
        lambda db: intake_mod.ChatModelConfig(client=object(), model="test-model", supports_vision=False),
    )
    monkeypatch.setattr(intake_mod, "gather_intake", lambda *a, **k: intake_mod.IntakeResult())

    async def go():
        gen = await runner_mod.run_turn_stream(db, user=user, request=request)
        return [c async for c in gen]

    return _parse_events(asyncio.run(go()))


def test_clarify_streams_and_persists_history(monkeypatch):
    user = make_user(ALL_FINANCIAL_PERMS)
    db = FakeDB()
    events = _collect(
        db, user, AssistantChatRequest(query="do the thing", chat_id=1), monkeypatch,
        intent="clarify", clarify="Which receipt do you mean?",
    )
    kinds = [e for e, _ in events]
    assert "delta" in kinds
    assert "done" in kinds
    # Both the user and assistant messages were written to the transcript (§8.1).
    roles = [getattr(m.role, "value", str(m.role)) for m in _MESSAGES]
    assert roles.count("user") == 1 and roles.count("assistant") == 1
    assistant_msg = [m for m in _MESSAGES if getattr(m.role, "value", str(m.role)) == "assistant"][0]
    assert "Which receipt" in assistant_msg.content
    # The run completed.
    runs = [o for o in db.added if isinstance(o, AgentRun)]
    assert runs and runs[0].status == AgentRunStatus.COMPLETED.value


def test_draft_streamed_as_whole_object_and_not_committed(monkeypatch):
    user = make_user(ALL_FINANCIAL_PERMS)
    db = FakeDB()

    async def fake_stream(state):
        for piece in ["Prepared ", "a draft."]:
            yield piece

    monkeypatch.setattr(runner_mod, "_stream_model_answer", fake_stream)

    slots = {
        "description": "pump", "amount": "100", "currency": "IRR", "direction": "output",
        "credit_card_id": 1, "receipt_date": "2026-06-01", "counterparty_name": "ACME",
    }
    events = _collect(
        db, user, AssistantChatRequest(query="add a receipt, yes do it", chat_id=1), monkeypatch,
        intent="add_receipt", slots=slots,
    )
    by_kind = {e: d for e, d in events}
    assert "draft" in by_kind
    assert by_kind["draft"]["draft"]["commit_target"]["endpoint"] == "/financial_management/receipts"

    drafts = [o for o in db.added if isinstance(o, Draft)]
    assert len(drafts) == 1
    # Chat text never commits: the persisted draft is pending, never committed (§10.5).
    assert drafts[0].status == DraftStatus.PENDING.value
    # done carries the draft_id so history can re-render it.
    done = by_kind["done"]
    assert done["draft_id"] == drafts[0].id


def test_midstream_failure_leaves_run_resumable(monkeypatch):
    user = make_user(ALL_FINANCIAL_PERMS)
    db = FakeDB()

    async def boom(state):
        raise RuntimeError("model exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(runner_mod, "_stream_model_answer", boom)

    events = _collect(
        db, user, AssistantChatRequest(query="what is OPEX?", chat_id=1), monkeypatch, intent="general",
    )
    kinds = [e for e, _ in events]
    assert "error" in kinds
    assert "done" not in kinds
    runs = [o for o in db.added if isinstance(o, AgentRun)]
    # Suspended = resumable; not completed/failed-terminal mid-stream.
    assert runs and runs[0].status == AgentRunStatus.SUSPENDED.value


def test_answer_messages_include_history():
    messages = runner_mod._answer_messages({
        "intent": "general",
        "language": "en",
        "question": "what about yesterday?",
        "history": [
            {"role": "user", "content": "We were discussing receipt 42."},
            {"role": "assistant", "content": "Receipt 42 was for pump repair."},
        ],
    })
    assert messages[1] == {"role": "user", "content": "We were discussing receipt 42."}
    assert messages[2] == {"role": "assistant", "content": "Receipt 42 was for pump repair."}
    assert messages[3] == {"role": "user", "content": "what about yesterday?"}


def test_answer_prompt_is_module_aware_not_finance_hardcoded():
    messages = runner_mod._answer_messages({
        "selected_module": "purchase_management",
        "selected_task": "search_purchase_orders",
        "intent": "search_purchase_orders",
        "language": "en",
        "question": "find PO-42",
        "history": [],
        "retrieved_items": [],
        "citations": [],
    })
    system = messages[0]["content"]
    assert "Current module: purchase_management" in system
    assert "financial-management assistant" not in system


def test_load_latest_partial_draft_from_prior_run():
    db = FakeDB()
    user = make_user(ALL_FINANCIAL_PERMS)
    partial = {
        "target_module": "financial_management",
        "target_action": "create_customer",
        "payload": {"name": "محمد مهدی آورا"},
    }
    db.set_all("AgentRun", [
        SimpleNamespace(
            chat_id=1,
            company_id=user.company_id,
            created_by_user_id=user.id,
            state={"partial_draft": partial},
        )
    ])
    assert runner_mod._load_latest_partial_draft(db, chat_id=1, user=user) == partial
