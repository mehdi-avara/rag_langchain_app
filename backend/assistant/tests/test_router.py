"""PROMPT §3 — intent router classification with the LLM mocked."""

import asyncio
import json
from types import SimpleNamespace

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, make_user

import financial_management.assistant_tools  # noqa: F401
from assistant import registry, router
from components.llm import llm_client


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content

    async def create(self, *args, **kwargs):
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def _install(monkeypatch, content: str):
    monkeypatch.setattr(llm_client, "_async_openai_client", _FakeClient(content))


def test_router_picks_permitted_intent(monkeypatch):
    _install(
        monkeypatch,
        json.dumps({"intent": "search_receipts", "language": "fa", "slots": {"query": "ACME"}, "clarify_question": None}),
    )
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    result = asyncio.run(router.classify(question="رسید ACME را پیدا کن", intents=intents))
    assert result["intent"] == "search_receipts"
    assert result["language"] == "fa"
    assert result["slots"]["query"] == "ACME"


def test_router_rejects_unpermitted_intent_falls_back_to_clarify(monkeypatch):
    # Model tries to route to add_receipt but the user lacks the permission, so
    # that intent isn't in the catalog -> fall back to clarify.
    _install(monkeypatch, json.dumps({"intent": "add_receipt", "language": "en", "slots": {}}))
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:receipts:create"]
    user = make_user(perms)
    intents = registry.assemble_intents(user)
    result = asyncio.run(router.classify(question="add a receipt", intents=intents))
    assert result["intent"] == "clarify"


def test_router_handles_malformed_json(monkeypatch):
    _install(monkeypatch, "not json at all")
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    result = asyncio.run(router.classify(question="???", intents=intents))
    assert result["intent"] == "clarify"
