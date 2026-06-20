import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

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

from Models import Chunk, Document
from routs import documents as document_routes
from schemas.search import DocumentAskRequest, SemanticSearchRequest, TextSearchRequest


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target
        self.filters = []
        self.ordered = False
        self.joined = False
        self.outer_joined = False

    def join(self, *args, **kwargs):
        self.joined = True
        return self

    def outerjoin(self, *args, **kwargs):
        self.outer_joined = True
        return self

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        self.ordered = True
        return self

    def first(self):
        if self.target is Chunk:
            return self.db.chunk_result
        if self.target is Document:
            return self.db.document_result
        return None

    def all(self):
        if self.target is Chunk:
            return self.db.chunk_rows
        if self.target is Document:
            return self.db.document_rows
        return []


class FakeDB:
    def __init__(self, document_rows=None, document_result=None, chunk_result=None, chunk_rows=None):
        self.document_rows = document_rows or []
        self.document_result = document_result
        self.chunk_result = chunk_result
        self.chunk_rows = chunk_rows or []
        self.queries = []

    def query(self, target):
        query = FakeQuery(self, target)
        self.queries.append(query)
        return query


def make_role(name="user", is_active=True):
    return SimpleNamespace(name=name, is_active=is_active)


def make_user(user_id=3, company_id=1, role="user", roles=None):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        role=role,
        roles=roles if roles is not None else [],
    )


def make_doc(doc_id=10, owner_id=3, filename="document.pdf"):
    return SimpleNamespace(
        id=doc_id,
        owner_id=owner_id,
        filename=filename,
        n_pages=2,
        n_chunks=3,
        status="done",
        abstract=None,
        current_version_id=1,
        file_path=str(doc_id),
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def make_chunk(chunk_id=5, doc_id=10, page_num=0):
    return SimpleNamespace(
        id=chunk_id,
        doc_id=doc_id,
        page_num=page_num,
        start_pos=0,
        end_pos=100,
        chunk_type="text",
        content="chunk content",
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def make_hit(document_id=10, part_id=5):
    return SimpleNamespace(
        document_id=document_id,
        document_title="document.pdf",
        part_id=part_id,
        part_text="matched text",
        createdAt=datetime(2026, 5, 16, 10, 0, 0),
        status="done",
        owner_id=3,
    )


@pytest.mark.asyncio
async def test_list_documents_returns_query_results_for_admin():
    docs = [make_doc(1), make_doc(2)]
    db = FakeDB(document_rows=docs)
    current_user = make_user(role="admin")

    result = await document_routes.list_documents(current_user=current_user, db=db)

    assert result == docs
    assert db.queries[0].joined is True
    assert db.queries[0].ordered is True


@pytest.mark.asyncio
async def test_list_documents_applies_access_filter_for_normal_user():
    docs = [make_doc(1)]
    db = FakeDB(document_rows=docs)
    current_user = make_user(role="user")

    result = await document_routes.list_documents(current_user=current_user, db=db)

    assert result == docs
    assert db.queries[0].joined is True
    assert db.queries[0].outer_joined is True
    assert db.queries[0].ordered is True


@pytest.mark.asyncio
async def test_filter_documents_passes_company_and_allowed_ids(monkeypatch):
    captured = {}

    def fake_allowed_ids(db, current_user, action):
        assert action == "read"
        return [1, 3, 5]

    def fake_search_documents_text(**kwargs):
        captured.update(kwargs)
        return ["result"]

    monkeypatch.setattr(document_routes, "_get_accessible_document_ids", fake_allowed_ids)
    monkeypatch.setattr(document_routes, "search_documents_text", fake_search_documents_text)

    payload = TextSearchRequest(query="contract", ids=[3, 4, 5], limit=20)
    current_user = make_user(company_id=7)
    db = object()

    result = await document_routes.filter_documents(payload=payload, current_user=current_user, db=db)

    assert result == ["result"]
    assert captured["db"] is db
    assert captured["query_text"] == "contract"
    assert captured["company_id"] == 7
    assert captured["doc_ids"] == [3, 5]
    assert captured["limit"] == 20


@pytest.mark.asyncio
async def test_filter_documents_allows_admin_requested_ids(monkeypatch):
    captured = {}

    monkeypatch.setattr(document_routes, "_get_accessible_document_ids", lambda *_args, **_kwargs: None)

    def fake_search_documents_text(**kwargs):
        captured.update(kwargs)
        return ["result"]

    monkeypatch.setattr(document_routes, "search_documents_text", fake_search_documents_text)

    payload = TextSearchRequest(query="contract", ids=[3, 4, 5], limit=20)
    current_user = make_user(company_id=7, role="admin")

    result = await document_routes.filter_documents(payload=payload, current_user=current_user, db=object())

    assert result == ["result"]
    assert captured["company_id"] == 7
    assert captured["doc_ids"] == [3, 4, 5]


@pytest.mark.asyncio
async def test_semantic_search_documents_passes_company_and_allowed_ids(monkeypatch):
    captured = {}

    monkeypatch.setattr(document_routes, "_get_accessible_document_ids", lambda *_args, **_kwargs: [2, 4, 6])

    def fake_semantic_search(**kwargs):
        captured.update(kwargs)
        return [make_hit(4)]

    monkeypatch.setattr(document_routes, "search_document_part_hits_semantic", fake_semantic_search)

    payload = SemanticSearchRequest(query="policy", ids=[4, 5, 6], limit=50)
    current_user = make_user(company_id=11)

    result = await document_routes.semantic_search_documents(
        payload=payload,
        top_k=12,
        current_user=current_user,
        db=object(),
    )

    assert len(result) == 1
    assert captured["query_text"] == "policy"
    assert captured["company_id"] == 11
    assert captured["doc_ids"] == [4, 6]
    assert captured["limit"] == 12


@pytest.mark.asyncio
async def test_ask_documents_uses_ask_access_and_returns_parsed_answer(monkeypatch):
    captured = {}

    monkeypatch.setattr(document_routes, "_get_accessible_document_ids", lambda *_args, **_kwargs: [10, 20])

    def fake_semantic_search(**kwargs):
        captured.update(kwargs)
        return [make_hit(10, 100)]

    async def fake_answer(question, references):
        assert question == "What is this?"
        assert len(references) == 1
        return "Answer text [100]"

    monkeypatch.setattr(document_routes, "search_document_part_hits_semantic", fake_semantic_search)
    monkeypatch.setattr(document_routes, "generate_answer_from_references", fake_answer)
    monkeypatch.setattr(document_routes, "parse_semantic_citations", lambda answer: ([100], [], [100]))

    payload = DocumentAskRequest(question="What is this?", scope="docs")
    current_user = make_user(company_id=2)

    result = await document_routes.ask_documents(payload=payload, current_user=current_user, db=object())

    assert result["answer"] == "Answer text [100]"
    assert result["citations"] == [100]
    assert result["used_chunk_ids"] == [100]
    assert result["used_comment_ids"] == []
    assert len(result["references"]) == 1
    assert captured["company_id"] == 2
    assert captured["doc_ids"] == [10, 20]
    assert captured["limit"] == 6


@pytest.mark.asyncio
async def test_ask_documents_skips_search_when_scope_comments(monkeypatch):
    called = {"search": False}

    def fake_semantic_search(**kwargs):
        called["search"] = True
        return []

    async def fake_answer(question, references):
        assert references == []
        return "No document search"

    monkeypatch.setattr(document_routes, "search_document_part_hits_semantic", fake_semantic_search)
    monkeypatch.setattr(document_routes, "generate_answer_from_references", fake_answer)
    monkeypatch.setattr(document_routes, "parse_semantic_citations", lambda answer: ([], [], []))

    payload = DocumentAskRequest(question="What is this?", scope="comments")
    current_user = make_user(company_id=2)

    result = await document_routes.ask_documents(payload=payload, current_user=current_user, db=object())

    assert result["answer"] == "No document search"
    assert called["search"] is False


@pytest.mark.asyncio
async def test_ask_documents_converts_llm_failure_to_504(monkeypatch):
    monkeypatch.setattr(document_routes, "_get_accessible_document_ids", lambda *_args, **_kwargs: [10])
    monkeypatch.setattr(document_routes, "search_document_part_hits_semantic", lambda **_kwargs: [make_hit(10)])

    async def fake_answer(question, references):
        raise RuntimeError("timeout")

    monkeypatch.setattr(document_routes, "generate_answer_from_references", fake_answer)

    payload = DocumentAskRequest(question="What is this?", scope="docs")

    with pytest.raises(HTTPException) as exc:
        await document_routes.ask_documents(payload=payload, current_user=make_user(), db=object())

    assert exc.value.status_code == 504
    assert "LLM request failed" in exc.value.detail


@pytest.mark.asyncio
async def test_get_chunk_returns_chunk_after_document_access_check(monkeypatch):
    chunk = make_chunk(chunk_id=8, doc_id=10, page_num=2)
    doc = make_doc(doc_id=10)
    db = FakeDB(chunk_result=chunk)

    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda *_args, **_kwargs: doc)

    result = await document_routes.get_chunk(chunk_id=8, current_user=make_user(), db=db)

    assert result["id"] == 8
    assert result["doc_id"] == 10
    assert result["page_num"] == 2
    assert result["content"] == "chunk content"


@pytest.mark.asyncio
async def test_get_chunk_raises_404_when_chunk_missing():
    db = FakeDB(chunk_result=None)

    with pytest.raises(HTTPException) as exc:
        await document_routes.get_chunk(chunk_id=999, current_user=make_user(), db=db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Chunk not found"


@pytest.mark.asyncio
async def test_browse_chunks_validates_page_range(monkeypatch):
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda *_args, **_kwargs: make_doc())

    with pytest.raises(HTTPException) as exc:
        await document_routes.browse_chunks(
            doc_id=10,
            start_page=5,
            end_page=3,
            current_user=make_user(),
            db=FakeDB(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "end_page must be greater than or equal to start_page"


@pytest.mark.asyncio
async def test_browse_chunks_returns_ordered_chunks(monkeypatch):
    chunks = [make_chunk(1, 10, 0), make_chunk(2, 10, 1)]
    db = FakeDB(chunk_rows=chunks)

    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda *_args, **_kwargs: make_doc())

    result = await document_routes.browse_chunks(
        doc_id=10,
        start_page=1,
        end_page=2,
        current_user=make_user(),
        db=db,
    )

    assert result == chunks
    assert db.queries[0].ordered is True
