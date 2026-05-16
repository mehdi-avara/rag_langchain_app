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

from Models import Comment, CommentFile, CommentType
from routs.comments import comment as comment_routes
from schemas.comment import CommentCreate, CommentUpdate
from schemas.search import (
    CommentAskRequest,
    SemanticCommentSearchRequestWithId,
    TextSearchRequest,
)


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target
        self.filters = []
        self.ordered = False

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        self.ordered = True
        return self

    def first(self):
        if self.target is Comment:
            return self.db.comment_result
        if self.target is CommentFile:
            return self.db.file_result
        return None

    def all(self):
        if self.target is Comment:
            return self.db.comment_rows
        if self.target is CommentFile:
            return self.db.file_rows
        return []


class FakeDB:
    def __init__(self, comment_result=None, comment_rows=None, file_result=None, file_rows=None):
        self.comment_result = comment_result
        self.comment_rows = comment_rows or []
        self.file_result = file_result
        self.file_rows = file_rows or []
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []
        self.queries = []

    def query(self, target):
        query = FakeQuery(self, target)
        self.queries.append(query)
        return query

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 100 + len(self.added)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 16, 10, 0, 0)
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_comment(comment_id=10, user_id=3, title="Title", content="Content", comment_type=CommentType.COMMENT):
    return SimpleNamespace(
        id=comment_id,
        user_id=user_id,
        title=title,
        content=content,
        type=comment_type,
        embedding=None,
        created_at=datetime(2026, 5, 16, 10, 0, 0),
        files=[],
    )


def make_hit(comment_id=10):
    return SimpleNamespace(
        comment_id=comment_id,
        comment_title="Title",
        comment_content="Content",
        type=CommentType.COMMENT,
        createdAt=datetime(2026, 5, 16, 10, 0, 0),
        userId=3,
    )


def test_get_owned_comment_returns_comment():
    comment = make_comment()
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    result = comment_routes._get_owned_comment(db, comment_id=10, current_user=current_user)

    assert result is comment


def test_get_owned_comment_raises_404_for_missing_or_other_user_comment():
    db = FakeDB(comment_result=None)
    current_user = make_user(user_id=3)

    with pytest.raises(HTTPException) as exc:
        comment_routes._get_owned_comment(db, comment_id=10, current_user=current_user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Comment not found"


def test_list_comments_returns_only_current_user_query_results():
    comments = [make_comment(1), make_comment(2)]
    db = FakeDB(comment_rows=comments)
    current_user = make_user(user_id=3)

    result = comment_routes.list_comments(db=db, current_user=current_user)

    assert result == comments
    assert db.queries[0].ordered is True


def test_filter_comments_passes_current_user_id_and_payload(monkeypatch):
    captured = {}

    def fake_search_comments_text(**kwargs):
        captured.update(kwargs)
        return ["result"]

    monkeypatch.setattr(comment_routes, "search_comments_text", fake_search_comments_text)

    payload = TextSearchRequest(query="repair", ids=[1, 2], limit=25)
    db = object()
    current_user = make_user(user_id=8)

    result = comment_routes.filter_comments(payload=payload, db=db, current_user=current_user)

    assert result == ["result"]
    assert captured["db"] is db
    assert captured["query_text"] == "repair"
    assert captured["user_id"] == 8
    assert captured["comment_ids"] == [1, 2]
    assert captured["limit"] == 25


def test_filter_comments_passes_none_for_empty_ids(monkeypatch):
    captured = {}

    def fake_search_comments_text(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(comment_routes, "search_comments_text", fake_search_comments_text)

    payload = TextSearchRequest(query="repair", ids=[], limit=25)
    current_user = make_user(user_id=8)

    result = comment_routes.filter_comments(payload=payload, db=object(), current_user=current_user)

    assert result == []
    assert captured["comment_ids"] is None


def test_semantic_search_comments_passes_user_ids_types_and_limit(monkeypatch):
    captured = {}

    def fake_search_comment_hits_semantic(**kwargs):
        captured.update(kwargs)
        return [make_hit(7)]

    monkeypatch.setattr(comment_routes, "search_comment_hits_semantic", fake_search_comment_hits_semantic)

    payload = SemanticCommentSearchRequestWithId(
        query="failure",
        ids=[7, 8],
        types=[CommentType.FAILURE],
    )
    current_user = make_user(user_id=9)

    result = comment_routes.semantic_search_comments(
        payload=payload,
        top_k=12,
        db=object(),
        current_user=current_user,
    )

    assert len(result) == 1
    assert captured["query_text"] == "failure"
    assert captured["user_id"] == 9
    assert captured["comment_ids"] == [7, 8]
    assert captured["types"] == [CommentType.FAILURE]
    assert captured["limit"] == 12


@pytest.mark.asyncio
async def test_ask_comments_uses_comment_scope_and_returns_parsed_answer(monkeypatch):
    captured = {}

    def fake_search_comment_hits_semantic(**kwargs):
        captured.update(kwargs)
        return [make_hit(5)]

    async def fake_answer(question, references):
        assert question == "What failed?"
        assert len(references) == 1
        return "Answer [5]"

    monkeypatch.setattr(comment_routes, "search_comment_hits_semantic", fake_search_comment_hits_semantic)
    monkeypatch.setattr(comment_routes, "generate_answer_from_references", fake_answer)
    monkeypatch.setattr(comment_routes, "parse_semantic_citations", lambda answer: ([], [5], [5]))

    payload = CommentAskRequest(
        question="What failed?",
        scope="comments",
        types=[CommentType.FAILURE],
    )
    current_user = make_user(user_id=4)

    result = await comment_routes.ask_comments(payload=payload, db=object(), current_user=current_user)

    assert result["answer"] == "Answer [5]"
    assert result["citations"] == [5]
    assert result["used_chunk_ids"] == []
    assert result["used_comment_ids"] == [5]
    assert len(result["references"]) == 1
    assert captured["query_text"] == "What failed?"
    assert captured["user_id"] == 4
    assert captured["comment_ids"] is None
    assert captured["types"] == [CommentType.FAILURE]
    assert captured["limit"] == 10


@pytest.mark.asyncio
async def test_ask_comments_skips_search_when_scope_docs(monkeypatch):
    called = {"search": False}

    def fake_search_comment_hits_semantic(**kwargs):
        called["search"] = True
        return []

    async def fake_answer(question, references):
        assert references == []
        return "No comment search"

    monkeypatch.setattr(comment_routes, "search_comment_hits_semantic", fake_search_comment_hits_semantic)
    monkeypatch.setattr(comment_routes, "generate_answer_from_references", fake_answer)
    monkeypatch.setattr(comment_routes, "parse_semantic_citations", lambda answer: ([], [], []))

    payload = CommentAskRequest(question="Question?", scope="docs")
    current_user = make_user(user_id=4)

    result = await comment_routes.ask_comments(payload=payload, db=object(), current_user=current_user)

    assert result["answer"] == "No comment search"
    assert called["search"] is False


def test_get_comment_by_id_uses_owned_comment():
    comment = make_comment()
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    result = comment_routes.get_comment_by_id(comment_id=10, db=db, current_user=current_user)

    assert result is comment


@pytest.mark.asyncio
async def test_create_comment_stores_current_user_and_embedding(monkeypatch):
    db = FakeDB()
    current_user = make_user(user_id=5)

    monkeypatch.setattr(comment_routes, "generate_embeddings_for_chunks", lambda chunks: [[0.1, 0.2]])

    payload = CommentCreate(
        title="Repair",
        content="Pump repaired",
        type=CommentType.REPAIRE,
    )

    result = await comment_routes.create_comment(payload=payload, db=db, current_user=current_user)

    assert db.committed is True
    assert db.refreshed == [result]
    assert result.user_id == 5
    assert result.title == "Repair"
    assert result.content == "Pump repaired"
    assert result.type == CommentType.REPAIRE
    assert result.embedding == [0.1, 0.2]


@pytest.mark.asyncio
async def test_create_comment_continues_when_embedding_fails(monkeypatch):
    db = FakeDB()
    current_user = make_user(user_id=5)

    def raise_embedding_error(chunks):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(comment_routes, "generate_embeddings_for_chunks", raise_embedding_error)

    payload = CommentCreate(title="Repair", content="Pump repaired", type=CommentType.REPAIRE)

    result = await comment_routes.create_comment(payload=payload, db=db, current_user=current_user)

    assert db.committed is True
    assert result.embedding is None


@pytest.mark.asyncio
async def test_update_comment_updates_fields_and_embedding(monkeypatch):
    comment = make_comment(title="Old", content="Old content", comment_type=CommentType.COMMENT)
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    monkeypatch.setattr(comment_routes, "generate_embeddings_for_chunks", lambda chunks: [[0.3, 0.4]])

    payload = CommentUpdate(
        title="New",
        content="New content",
        type=CommentType.REPORT,
    )

    result = await comment_routes.update_comment(
        comment_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result is comment
    assert comment.title == "New"
    assert comment.content == "New content"
    assert comment.type == CommentType.REPORT
    assert comment.embedding == [0.3, 0.4]
    assert db.committed is True
    assert db.refreshed == [comment]


@pytest.mark.asyncio
async def test_update_comment_does_not_reembed_when_content_not_changed(monkeypatch):
    comment = make_comment(title="Old", content="Old content")
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)
    called = {"embedding": False}

    def fake_embedding(chunks):
        called["embedding"] = True
        return [[0.3]]

    monkeypatch.setattr(comment_routes, "generate_embeddings_for_chunks", fake_embedding)

    payload = CommentUpdate(title="Only title changed")

    result = await comment_routes.update_comment(
        comment_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result.title == "Only title changed"
    assert result.content == "Old content"
    assert called["embedding"] is False


@pytest.mark.asyncio
async def test_update_comment_sets_embedding_none_when_embedding_fails(monkeypatch):
    comment = make_comment()
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    def raise_embedding_error(chunks):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(comment_routes, "generate_embeddings_for_chunks", raise_embedding_error)

    payload = CommentUpdate(content="New content")

    result = await comment_routes.update_comment(
        comment_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result.embedding is None
    assert result.content == "New content"


def test_delete_comment_deletes_owned_comment():
    comment = make_comment()
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    result = comment_routes.delete_comment(comment_id=10, db=db, current_user=current_user)

    assert result is None
    assert db.deleted == [comment]
    assert db.committed is True
