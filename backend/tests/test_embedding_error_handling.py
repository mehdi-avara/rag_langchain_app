import os
from types import SimpleNamespace

import pytest

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

from components.embedding import JinaAPIEmbeddings
from core.exceptions import AppException
from core.exceptions.error_codes import (
    EMBEDDING_BAD_RESPONSE,
    EMBEDDING_SERVICE_UNAVAILABLE,
    SERVICE_UNAVAILABLE_STATUS_CODE,
)


class FakeResponse:
    def __init__(self, payload=None, raise_exc=None):
        self.payload = payload or {}
        self.raise_exc = raise_exc

    def raise_for_status(self):
        if self.raise_exc:
            raise self.raise_exc

    def json(self):
        return self.payload


def test_embedding_fail_soft_returns_empty_list(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("components.embedding.requests.post", fake_post)
    monkeypatch.setattr("components.embedding.log_embedding_error", lambda record: None)

    embeddings = JinaAPIEmbeddings(fail_soft=True)

    assert embeddings.embed_documents(["hello"]) == []
    assert embeddings.embed_query("hello") == []


def test_embedding_strict_raises_standard_unavailable_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("components.embedding.requests.post", fake_post)
    monkeypatch.setattr("components.embedding.log_embedding_error", lambda record: None)

    embeddings = JinaAPIEmbeddings(fail_soft=False)

    with pytest.raises(AppException) as exc:
        embeddings.embed_documents(["hello"])

    assert exc.value.status_code == SERVICE_UNAVAILABLE_STATUS_CODE
    assert exc.value.code == EMBEDDING_SERVICE_UNAVAILABLE
    assert exc.value.detail["code"] == EMBEDDING_SERVICE_UNAVAILABLE
    assert exc.value.detail["details"]["context"] == "embed_documents"


def test_embedding_strict_raises_bad_response_error(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"unexpected": []})

    monkeypatch.setattr("components.embedding.requests.post", fake_post)
    monkeypatch.setattr("components.embedding.log_embedding_error", lambda record: None)

    embeddings = JinaAPIEmbeddings(fail_soft=False)

    with pytest.raises(AppException) as exc:
        embeddings.embed_documents(["hello"])

    assert exc.value.status_code == SERVICE_UNAVAILABLE_STATUS_CODE
    assert exc.value.code == EMBEDDING_BAD_RESPONSE
    assert exc.value.detail["code"] == EMBEDDING_BAD_RESPONSE


def test_embedding_strict_query_raises_standard_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("components.embedding.requests.post", fake_post)
    monkeypatch.setattr("components.embedding.log_embedding_error", lambda record: None)

    embeddings = JinaAPIEmbeddings(fail_soft=False)

    with pytest.raises(AppException) as exc:
        embeddings.embed_query("hello")

    assert exc.value.code == EMBEDDING_SERVICE_UNAVAILABLE
