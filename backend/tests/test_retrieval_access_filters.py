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

from retrieval.vector.postgres_store import PostgresVectorStore
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB


class FakeEmbeddings:
    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


class FakeExecuteResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeVectorDB:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed_sql = None
        self.executed_params = None
        self.execute_called = False

    def execute(self, sql, params):
        self.execute_called = True
        self.executed_sql = str(sql)
        self.executed_params = params
        return FakeExecuteResult(self.rows)


class FakeKeywordQuery:
    def __init__(self):
        self.filters = []
        self.joins = []
        self.return_rows = []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def join(self, *args):
        self.joins.extend(args)
        return self

    def all(self):
        return self.return_rows


class FakeKeywordDB:
    def __init__(self):
        self.query_obj = FakeKeywordQuery()

    def query(self, *args):
        return self.query_obj


def test_vector_similarity_search_returns_empty_when_doc_ids_empty():
    db = FakeVectorDB()
    store = PostgresVectorStore.__new__(PostgresVectorStore)
    store.db = db
    store.embeddings = FakeEmbeddings()

    result = store.similarity_search(
        query="question",
        k=6,
        doc_ids=[],
        company_id=4,
    )

    assert result == []
    assert db.execute_called is False


def test_vector_similarity_search_applies_company_and_doc_id_filters():
    db = FakeVectorDB(rows=[])
    store = PostgresVectorStore.__new__(PostgresVectorStore)
    store.db = db
    store.embeddings = FakeEmbeddings()

    result = store.similarity_search(
        query="question",
        k=6,
        doc_ids=[3, 5],
        company_id=4,
    )

    assert result == []
    assert db.execute_called is True
    assert "JOIN documents d ON d.id = c.doc_id" in db.executed_sql
    assert "JOIN users u ON u.id = d.owner_id" in db.executed_sql
    assert "u.company_id = :company_id" in db.executed_sql
    assert "c.doc_id IN (:doc_id_0, :doc_id_1)" in db.executed_sql
    assert db.executed_params["company_id"] == 4
    assert db.executed_params["doc_id_0"] == 3
    assert db.executed_params["doc_id_1"] == 5


def test_vector_comment_search_returns_empty_when_comment_ids_empty():
    db = FakeVectorDB()
    store = PostgresVectorStore.__new__(PostgresVectorStore)
    store.db = db
    store.embeddings = FakeEmbeddings()

    result = store.similarity_search_comments(
        query="question",
        k=6,
        comment_ids=[],
        company_id=4,
    )

    assert result == []
    assert db.execute_called is False


def test_vector_comment_search_applies_company_and_comment_id_filters():
    db = FakeVectorDB(rows=[])
    store = PostgresVectorStore.__new__(PostgresVectorStore)
    store.db = db
    store.embeddings = FakeEmbeddings()

    result = store.similarity_search_comments(
        query="question",
        k=6,
        comment_ids=[31, 32],
        company_id=4,
    )

    assert result == []
    assert db.execute_called is True
    assert "JOIN users u ON u.id = c.user_id" in db.executed_sql
    assert "u.company_id = :company_id" in db.executed_sql
    assert "c.id IN (:id_0, :id_1)" in db.executed_sql
    assert db.executed_params["company_id"] == 4
    assert db.executed_params["id_0"] == 31
    assert db.executed_params["id_1"] == 32


@pytest.mark.asyncio
async def test_keyword_retriever_returns_empty_when_doc_ids_empty():
    db = FakeKeywordDB()
    retriever = FullTextRetrieverFromDB(db)

    result = await retriever.ainvoke(
        "question",
        doc_ids=[],
        company_id=4,
    )

    assert result == []


@pytest.mark.asyncio
async def test_keyword_retriever_applies_filters_when_doc_ids_present():
    db = FakeKeywordDB()
    retriever = FullTextRetrieverFromDB(db)

    await retriever.ainvoke(
        "question",
        doc_ids=[3, 5],
        company_id=4,
    )

    assert len(db.query_obj.joins) >= 2
    assert len(db.query_obj.filters) >= 3
