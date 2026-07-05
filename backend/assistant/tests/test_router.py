"""PROMPT §3 — intent router classification with the LLM mocked."""

import asyncio
import json
from types import SimpleNamespace

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, make_user

import financial_management.assistant_tools  # noqa: F401
from assistant import registry, router
from components.llm import llm_client


class _FakeCompletions:
    def __init__(self, content: str, sink: dict):
        self._content = content
        self._sink = sink

    async def create(self, *args, **kwargs):
        self._sink["messages"] = kwargs.get("messages")
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    def __init__(self, content: str):
        self.captured: dict = {}
        self.chat = SimpleNamespace(completions=_FakeCompletions(content, self.captured))


def _install(monkeypatch, content: str) -> _FakeClient:
    client = _FakeClient(content)
    monkeypatch.setattr(llm_client, "_async_openai_client", client)
    return client


def _has_image_block(messages) -> bool:
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            return True
    return False


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


def test_router_sends_history_before_current_message(monkeypatch):
    client = _install(
        monkeypatch,
        json.dumps({"intent": "add_receipt", "language": "en", "slots": {}, "clarify_question": None}),
    )
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    asyncio.run(
        router.classify(
            question="from Mellat card yesterday",
            intents=intents,
            history=[
                {"role": "user", "content": "I want to add a receipt for ACME"},
                {"role": "assistant", "content": "I still need: receipt date, credit card."},
            ],
        )
    )
    messages = client.captured["messages"]
    assert messages[1] == {"role": "user", "content": "I want to add a receipt for ACME"}
    assert messages[2] == {"role": "assistant", "content": "I still need: receipt date, credit card."}
    assert messages[3] == {"role": "user", "content": "from Mellat card yesterday"}


def test_router_accepts_markdown_fenced_json(monkeypatch):
    _install(
        monkeypatch,
        """```json
{
  "intent": "add_receipt",
  "language": "fa",
  "slots": {
    "amount": 1000,
    "currency": "IRT",
    "counterparty": "محمد مهدی آورا",
    "description": "خرید قطعه پمپ",
    "credit_card_query": "کارت ملت شرکت",
    "date": "1405/04/14",
    "direction": "out"
  },
  "clarify_question": null
}
```""",
    )
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    result = asyncio.run(router.classify(question="یک رسید ثبت کن", intents=intents))
    assert result["intent"] == "add_receipt"
    assert result["language"] == "fa"
    assert result["slots"]["amount"] == 1000
    assert result["slots"]["direction"] == "out"


def test_capability_question_routes_without_llm(monkeypatch):
    class _ExplodingClient:
        class chat:
            class completions:
                @staticmethod
                async def create(*args, **kwargs):  # pragma: no cover - must not run
                    raise AssertionError("capability questions should not call the LLM router")

    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    result = asyncio.run(
        router.classify(
            question="what can you do?",
            intents=intents,
            client=_ExplodingClient(),
        )
    )
    assert result["intent"] == "assistant_help"
    assert result["slots"] == {}


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


def test_router_sends_image_blocks_to_vlm(monkeypatch):
    client = _install(monkeypatch, '{"intent": "add_receipt", "language": "en", "slots": {"amount": "500"}}')
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    img = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"}}]
    asyncio.run(router.classify(question="add this receipt", intents=intents, image_blocks=img))
    # The receipt photo is actually sent to the model.
    assert _has_image_block(client.captured["messages"]) is True


def test_router_text_only_without_images(monkeypatch):
    client = _install(monkeypatch, '{"intent": "search_receipts", "language": "en", "slots": {}}')
    user = make_user(ALL_FINANCIAL_PERMS)
    intents = registry.assemble_intents(user)
    asyncio.run(router.classify(question="find ACME", intents=intents))
    assert _has_image_block(client.captured["messages"]) is False
