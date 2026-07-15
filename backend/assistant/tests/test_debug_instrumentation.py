import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, FakeDB, make_user

import financial_management.assistant_tools  # noqa: F401
from assistant import intake as intake_mod
from assistant import router as router_mod
from assistant import runner as runner_mod
from assistant.models import AgentRun, AssistantEvent
from assistant.schemas import AssistantChatRequest


def _install_chat(monkeypatch):
    module = ModuleType("routs.chat")
    counter = iter((101, 102, 103, 104))
    messages = []

    def get_or_create_chat(db, *, chat_id, user):
        return SimpleNamespace(id=chat_id or 1), False

    def add_message(db, *, chat_id, role, content, citations=None, retrieved_chunks=None, draft_id=None):
        message = SimpleNamespace(
            id=next(counter), chat_id=chat_id, role=role, content=content,
            citations=citations, retrieved_chunks=retrieved_chunks, draft_id=draft_id,
        )
        messages.append(message)
        return message

    module.get_or_create_chat = get_or_create_chat
    module.add_message = add_message
    monkeypatch.setitem(sys.modules, "routs.chat", module)
    return messages


def _events(db):
    return sorted(
        [item for item in db.added if isinstance(item, AssistantEvent)],
        key=lambda item: item.sequence,
    )


def test_successful_turn_records_distinct_hierarchy_stages_models_tools_and_output(monkeypatch):
    messages = _install_chat(monkeypatch)
    db = FakeDB()
    db.set_all("AgentRun", [])
    user = make_user(ALL_FINANCIAL_PERMS)

    async def classify_module(**kwargs):
        return {"module": "general", "language": "en", "confidence": 0.99, "clarify_question": None}

    async def answer(state):
        for value in ("observable ", "answer"):
            yield value

    monkeypatch.setattr(router_mod, "classify_module", classify_module)
    monkeypatch.setattr(
        intake_mod, "resolve_chat_model",
        lambda db: intake_mod.ChatModelConfig(client=object(), model="answer-model", supports_vision=False),
    )
    monkeypatch.setattr(intake_mod, "gather_intake", lambda *args, **kwargs: intake_mod.IntakeResult())
    monkeypatch.setattr(runner_mod, "_stream_model_answer", answer)

    async def execute():
        stream = await runner_mod.run_turn_stream(
            db, user=user, request=AssistantChatRequest(query="What is OPEX?", chat_id=1),
        )
        return [chunk async for chunk in stream]

    chunks = asyncio.run(execute())
    assert any("event: done" in chunk for chunk in chunks)
    run = next(item for item in db.added if isinstance(item, AgentRun))
    events = _events(db)
    types = [event.event_type for event in events]
    assert {
        "chat.started", "run.started", "module_router.started", "module_router.selected",
        "task_finder.started", "task_finder.selected", "executor.started", "executor.completed",
        "tool.started", "tool.completed", "validator.started", "validator.completed",
        "answer.started", "answer.completed", "model.started", "model.completed", "run.completed",
    } <= set(types)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert {event.agent_run_id for event in events} == {run.id}
    assert {event.message_id for event in events} == {101}
    assert run.input_message_id == 101
    assert run.output_message_id == 102
    assert run.current_stage == "completed"
    assert messages[-1].content == "observable answer"


def test_failed_answer_keeps_resumable_status_and_records_failed_timeline(monkeypatch):
    _install_chat(monkeypatch)
    db = FakeDB()
    db.set_all("AgentRun", [])
    user = make_user(ALL_FINANCIAL_PERMS)

    async def classify_module(**kwargs):
        return {"module": "general", "language": "en", "confidence": 0.8, "clarify_question": None}

    async def answer(state):
        raise RuntimeError("provider failed")
        yield  # pragma: no cover

    monkeypatch.setattr(router_mod, "classify_module", classify_module)
    monkeypatch.setattr(
        intake_mod, "resolve_chat_model",
        lambda db: intake_mod.ChatModelConfig(client=object(), model="answer-model", supports_vision=False),
    )
    monkeypatch.setattr(intake_mod, "gather_intake", lambda *args, **kwargs: intake_mod.IntakeResult())
    monkeypatch.setattr(runner_mod, "_stream_model_answer", answer)

    async def execute():
        stream = await runner_mod.run_turn_stream(
            db, user=user, request=AssistantChatRequest(query="fail", chat_id=1),
        )
        return [chunk async for chunk in stream]

    chunks = asyncio.run(execute())
    run = next(item for item in db.added if isinstance(item, AgentRun))
    types = [event.event_type for event in _events(db)]
    assert any("event: error" in chunk for chunk in chunks)
    assert "model.failed" in types
    assert "run.failed" in types
    assert "run.completed" not in types
    # Backward-compatible behavior: streaming failures remain resumable.
    assert run.status == "suspended"


def test_two_user_messages_create_separate_runs_and_never_mix_events(monkeypatch):
    _install_chat(monkeypatch)
    db = FakeDB()
    db.set_all("AgentRun", [])
    user = make_user(ALL_FINANCIAL_PERMS)

    async def classify_module(**kwargs):
        return {"module": "general", "language": "en", "confidence": 0.9, "clarify_question": None}

    async def answer(state):
        yield "answer"

    monkeypatch.setattr(router_mod, "classify_module", classify_module)
    monkeypatch.setattr(
        intake_mod, "resolve_chat_model",
        lambda db: intake_mod.ChatModelConfig(client=object(), model="answer-model", supports_vision=False),
    )
    monkeypatch.setattr(intake_mod, "gather_intake", lambda *args, **kwargs: intake_mod.IntakeResult())
    monkeypatch.setattr(runner_mod, "_stream_model_answer", answer)

    async def turn(query):
        stream = await runner_mod.run_turn_stream(
            db, user=user, request=AssistantChatRequest(query=query, chat_id=1),
        )
        return [chunk async for chunk in stream]

    asyncio.run(turn("first user message"))
    asyncio.run(turn("second user message"))

    runs = [item for item in db.added if isinstance(item, AgentRun)]
    assert len(runs) == 2
    assert [(run.input_message_id, run.output_message_id) for run in runs] == [(101, 102), (103, 104)]
    events = _events(db)
    by_run = {
        run.id: [event for event in events if event.agent_run_id == run.id]
        for run in runs
    }
    assert all(by_run[run.id] for run in runs)
    assert {event.message_id for event in by_run[runs[0].id]} == {101}
    assert {event.message_id for event in by_run[runs[1].id]} == {103}
    assert [event.sequence for event in by_run[runs[0].id]] == list(range(1, len(by_run[runs[0].id]) + 1))
    assert [event.sequence for event in by_run[runs[1].id]] == list(range(1, len(by_run[runs[1].id]) + 1))
