import os
from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableLambda

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin123456")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

from components.llm import LLMClient
from core.exceptions import AppException
from core.exceptions.error_codes import (
    GATEWAY_TIMEOUT_STATUS_CODE,
    LLM_REQUEST_TIMEOUT,
    LLM_SERVICE_UNAVAILABLE,
    SERVICE_UNAVAILABLE_STATUS_CODE,
)
from core import semantic_ask
from core.agents import langgraph


class FailingCompletions:
    def __init__(self, exc):
        self.exc = exc

    async def create(self, *args, **kwargs):
        raise self.exc


def fake_openai_client(exc):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=FailingCompletions(exc),
        )
    )


@pytest.mark.asyncio
async def test_llm_client_rewrite_query_returns_standard_unavailable_error():
    client = LLMClient()
    client._async_openai_client = fake_openai_client(RuntimeError("connection refused"))

    with pytest.raises(AppException) as exc:
        await client.rewrite_query("hello")

    assert exc.value.status_code == SERVICE_UNAVAILABLE_STATUS_CODE
    assert exc.value.code == LLM_SERVICE_UNAVAILABLE
    assert exc.value.detail["code"] == LLM_SERVICE_UNAVAILABLE
    assert exc.value.detail["details"]["context"] == "rewrite_query"


@pytest.mark.asyncio
async def test_llm_client_extract_keywords_returns_timeout_error():
    client = LLMClient()
    client._async_openai_client = fake_openai_client(TimeoutError("request timeout"))

    with pytest.raises(AppException) as exc:
        await client.extract_keywords("hello")

    assert exc.value.status_code == GATEWAY_TIMEOUT_STATUS_CODE
    assert exc.value.code == LLM_REQUEST_TIMEOUT
    assert exc.value.detail["code"] == LLM_REQUEST_TIMEOUT
    assert exc.value.detail["details"]["context"] == "extract_keywords"


@pytest.mark.asyncio
async def test_semantic_ask_returns_standard_llm_error(monkeypatch):
    monkeypatch.setattr(
        semantic_ask,
        "llm_client",
        SimpleNamespace(async_openai_client=fake_openai_client(RuntimeError("down"))),
    )

    with pytest.raises(AppException) as exc:
        await semantic_ask.generate_answer_from_references("question", [])

    assert exc.value.status_code == SERVICE_UNAVAILABLE_STATUS_CODE
    assert exc.value.code == LLM_SERVICE_UNAVAILABLE
    assert exc.value.detail["details"]["context"] == "generate_answer_from_references"


@pytest.mark.asyncio
async def test_langgraph_generate_answer_returns_standard_llm_error(monkeypatch):
    async def fail_llm(_input):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        langgraph,
        "llm_client",
        SimpleNamespace(langchain_llm=RunnableLambda(fail_llm)),
    )

    state = {
        "question": "question",
        "route": "full",
        "chunks": [],
        "comments": [],
        "answer": "",
        "citations": [],
        "mode": "vector",
        "db": None,
        "doc_ids": [],
        "comment_ids": [],
        "company_id": 1,
        "scope": "both",
    }

    with pytest.raises(AppException) as exc:
        await langgraph.generate_answer(state)

    assert exc.value.status_code == SERVICE_UNAVAILABLE_STATUS_CODE
    assert exc.value.code == LLM_SERVICE_UNAVAILABLE
    assert exc.value.detail["details"]["context"] == "chat_generate_answer"
