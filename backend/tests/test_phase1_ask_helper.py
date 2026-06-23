from __future__ import annotations

import asyncio
from types import SimpleNamespace

import shared.phase1_ask as phase1_ask


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="The RFQ is open. [rfq:7]"
                    )
                )
            ]
        )


def test_parse_citations_deduplicates_and_scopes_prefix():
    answer = "[rfq:7] [rfq:7] [rfq:12] [stock:3]"

    assert phase1_ask.parse_citations(answer, "rfq") == [7, 12]
    assert phase1_ask.parse_citations(answer, "stock") == [3]
    assert phase1_ask.parse_citations(answer, "grn") == []


def test_answer_from_references_uses_llm_and_citation_contract(monkeypatch):
    completions = FakeCompletions()

    fake_llm_client = SimpleNamespace(
        async_openai_client=SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
    )

    monkeypatch.setattr(
        phase1_ask,
        "llm_client",
        fake_llm_client,
    )

    answer = asyncio.run(
        phase1_ask.answer_from_references(
            question="What is the RFQ status?",
            references=[],
            context="[rfq:7] status=open",
            citation_prefix="rfq",
            component_name="phase1_ask_test",
        )
    )

    assert answer == "The RFQ is open. [rfq:7]"
    assert len(completions.calls) == 1

    messages = completions.calls[0]["messages"]

    assert "[rfq:<id>]" in messages[0]["content"]
    assert "What is the RFQ status?" in messages[1]["content"]
    assert "[rfq:7] status=open" in messages[1]["content"]
