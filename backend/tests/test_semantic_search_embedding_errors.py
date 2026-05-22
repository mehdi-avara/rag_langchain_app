import os

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

from core.exceptions import AppException
from core.exceptions.error_codes import EMBEDDING_SERVICE_UNAVAILABLE
from db import search_connector
from financial_management.search import repository as financial_search_repository


class FailingEmbeddingClient:
    def embed_query(self, text):
        raise AppException(
            status_code=503,
            code=EMBEDDING_SERVICE_UNAVAILABLE,
            message="Embedding service is unavailable",
            details={"context": "embed_query", "error_type": "RuntimeError"},
        )


def test_document_semantic_search_propagates_embedding_error(monkeypatch):
    monkeypatch.setattr(search_connector, "_embedding_client", lambda: FailingEmbeddingClient())

    with pytest.raises(AppException) as exc:
        search_connector.search_document_part_hits_semantic(
            db=None,
            query_text="hello",
            company_id=1,
        )

    assert exc.value.code == EMBEDDING_SERVICE_UNAVAILABLE


def test_comment_semantic_search_propagates_embedding_error(monkeypatch):
    monkeypatch.setattr(search_connector, "_embedding_client", lambda: FailingEmbeddingClient())

    with pytest.raises(AppException) as exc:
        search_connector.search_comment_hits_semantic(
            db=None,
            query_text="hello",
            company_id=1,
        )

    assert exc.value.code == EMBEDDING_SERVICE_UNAVAILABLE


def test_financial_receipt_semantic_search_propagates_embedding_error(monkeypatch):
    monkeypatch.setattr(financial_search_repository, "_embedding_client", lambda: FailingEmbeddingClient())

    with pytest.raises(AppException) as exc:
        financial_search_repository.search_financial_receipt_hits_semantic(
            db=None,
            query_text="hello",
            company_id=1,
        )

    assert exc.value.code == EMBEDDING_SERVICE_UNAVAILABLE
