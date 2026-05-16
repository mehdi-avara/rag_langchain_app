import os
from types import SimpleNamespace

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

from model_management.routes import models as model_routes
from tag_management.routes import tags as tag_routes
from tag_management.routes import ask as tag_ask_routes
from model_management.schemas import ModelAskRequest
from tag_management.schemas import TagAskMultiRequest
from schemas.search import TextSearchRequest


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, comment_rows):
        self.comment_rows = comment_rows

    def query(self, *targets):
        return FakeQuery(self.comment_rows)


def make_user(user_id=7, company_id=4):
    return SimpleNamespace(id=user_id, company_id=company_id)


def test_model_semantic_scope_intersects_documents_and_owned_comments(monkeypatch):
    db = FakeDB(comment_rows=[(10,), (12,)])
    current_user = make_user()

    monkeypatch.setattr(model_routes, "require_company", lambda current_user: current_user.company_id)
    monkeypatch.setattr(model_routes, "get_doc_ids_for_models", lambda db, model_ids: [1, 2, 3, 4])
    monkeypatch.setattr(model_routes, "get_comment_ids_for_models", lambda db, model_ids: [10, 11, 12])
    monkeypatch.setattr(model_routes, "_get_accessible_document_ids", lambda db, user, action: [2, 4, 8])
    monkeypatch.setattr(model_routes, "get_model_info_map", lambda db, model_ids, company_id: {})
    monkeypatch.setattr(model_routes, "get_doc_to_model_map", lambda db, model_ids: {})
    monkeypatch.setattr(model_routes, "get_comment_to_model_map", lambda db, model_ids: {})

    captured = {}

    def fake_document_search(**kwargs):
        captured["doc_ids"] = kwargs["doc_ids"]
        return []

    def fake_comment_search(**kwargs):
        captured["comment_ids"] = kwargs["comment_ids"]
        captured["user_id"] = kwargs["user_id"]
        return []

    monkeypatch.setattr(model_routes, "search_document_part_hits_semantic", fake_document_search)
    monkeypatch.setattr(model_routes, "search_comment_hits_semantic", fake_comment_search)

    result = model_routes._semantic_search_model_scope(
        db=db,
        current_user=current_user,
        query="pump",
        model_ids=[100],
        doc_top_k=5,
        comment_top_k=5,
        types=[],
    )

    assert result == {"documents": [], "comments": []}
    assert captured["doc_ids"] == [2, 4]
    assert captured["comment_ids"] == [10, 12]
    assert captured["user_id"] == 7


def test_model_filter_intersects_documents_and_owned_comments(monkeypatch):
    db = FakeDB(comment_rows=[(10,), (12,)])
    current_user = make_user()
    model = SimpleNamespace(id=100)

    monkeypatch.setattr(model_routes, "get_model_or_404", lambda db, model_id, current_user: model)
    monkeypatch.setattr(model_routes, "get_doc_ids", lambda db, model_id: [1, 2, 3, 4])
    monkeypatch.setattr(model_routes, "get_comment_ids", lambda db, model_id: [10, 11, 12])
    monkeypatch.setattr(model_routes, "_get_accessible_document_ids", lambda db, user, action: [2, 4, 8])

    captured = {}

    def fake_document_search(**kwargs):
        captured["doc_ids"] = kwargs["doc_ids"]
        captured["owner_id"] = kwargs.get("owner_id")
        return []

    def fake_comment_search(**kwargs):
        captured["comment_ids"] = kwargs["comment_ids"]
        captured["user_id"] = kwargs["user_id"]
        return []

    monkeypatch.setattr(model_routes, "search_documents_text", fake_document_search)
    monkeypatch.setattr(model_routes, "search_comments_text", fake_comment_search)

    result = model_routes.filter_model_content(
        model_id=100,
        payload=TextSearchRequest(query="pump"),
        db=db,
        current_user=current_user,
    )

    assert result == {"documents": [], "comments": []}
    assert captured["doc_ids"] == [2, 4]
    assert captured["owner_id"] is None
    assert captured["comment_ids"] == [10, 12]
    assert captured["user_id"] == 7


def test_tag_semantic_scope_intersects_documents_and_owned_comments(monkeypatch):
    db = FakeDB(comment_rows=[(20,), (22,)])
    current_user = make_user()

    monkeypatch.setattr(tag_routes, "get_doc_ids_for_tags", lambda db, tag_ids: [1, 2])
    monkeypatch.setattr(tag_routes, "get_comment_ids_for_tags", lambda db, tag_ids: [20, 21, 22])
    monkeypatch.setattr(tag_routes, "get_model_ids_for_tags", lambda db, tag_ids: [300])
    monkeypatch.setattr(tag_routes, "get_model_document_ids", lambda db, model_ids: [3, 4])
    monkeypatch.setattr(tag_routes, "_get_accessible_document_ids", lambda db, user, action: [2, 4, 9])
    monkeypatch.setattr(tag_routes, "get_tag_info_map", lambda db, tag_ids, company_id: {})
    monkeypatch.setattr(tag_routes, "get_model_info_map", lambda db, model_ids, company_id: {})
    monkeypatch.setattr(tag_routes, "get_doc_to_tag_map", lambda db, tag_ids: {})
    monkeypatch.setattr(tag_routes, "get_comment_to_tag_map", lambda db, tag_ids: {})
    monkeypatch.setattr(tag_routes, "get_doc_to_model_map", lambda db, model_ids: {})
    monkeypatch.setattr(tag_routes, "get_tag_to_model_map", lambda db, tag_ids: {})

    captured = {}

    def fake_document_search(**kwargs):
        captured["doc_ids"] = kwargs["doc_ids"]
        captured["company_id"] = kwargs.get("company_id")
        return []

    def fake_comment_search(**kwargs):
        captured["comment_ids"] = kwargs["comment_ids"]
        captured["user_id"] = kwargs["user_id"]
        captured["company_id"] = kwargs.get("company_id")
        return []

    monkeypatch.setattr(tag_routes, "search_document_part_hits_semantic", fake_document_search)
    monkeypatch.setattr(tag_routes, "search_comment_hits_semantic", fake_comment_search)

    result = tag_routes._semantic_search_tag_scope(
        db=db,
        current_user=current_user,
        query="pump",
        tag_ids=[200],
        doc_top_k=5,
        comment_top_k=5,
        types=[],
    )

    assert result == {"tags": [], "documents": [], "comments": []}
    assert captured["doc_ids"] == [2, 4]
    assert captured["company_id"] is None
    assert captured["comment_ids"] == [20, 22]
    assert captured["user_id"] == 7


def test_tag_filter_intersects_documents_and_owned_comments(monkeypatch):
    db = FakeDB(comment_rows=[(20,), (22,)])
    current_user = make_user()

    monkeypatch.setattr(tag_routes, "get_tag_or_404", lambda db, tag_id, current_user: SimpleNamespace(id=tag_id))
    monkeypatch.setattr(tag_routes, "get_doc_ids", lambda db, tag_id: [1, 2, 3])
    monkeypatch.setattr(tag_routes, "get_comment_ids", lambda db, tag_id: [20, 21, 22])
    monkeypatch.setattr(tag_routes, "_get_accessible_document_ids", lambda db, user, action: [2, 4, 8])

    captured = {}

    def fake_document_search(**kwargs):
        captured["doc_ids"] = kwargs["doc_ids"]
        captured["company_id"] = kwargs.get("company_id")
        return []

    def fake_comment_search(**kwargs):
        captured["comment_ids"] = kwargs["comment_ids"]
        captured["user_id"] = kwargs["user_id"]
        captured["company_id"] = kwargs.get("company_id")
        return []

    monkeypatch.setattr(tag_routes, "search_documents_text", fake_document_search)
    monkeypatch.setattr(tag_routes, "search_comments_text", fake_comment_search)

    result = tag_routes.filter_tag_content(
        tag_id=200,
        payload=TextSearchRequest(query="pump"),
        db=db,
        current_user=current_user,
    )

    assert result == {"documents": [], "comments": []}
    assert captured["doc_ids"] == [2]
    assert captured["company_id"] is None
    assert captured["comment_ids"] == [20, 22]
    assert captured["user_id"] == 7


def test_tag_ask_multi_validates_tags_with_current_user(monkeypatch):
    current_user = make_user()
    db = FakeDB(comment_rows=[])

    calls = []

    def fake_get_tag_or_404(db, tag_id, current_user_arg):
        calls.append((tag_id, current_user_arg))
        return SimpleNamespace(id=tag_id)

    async def fake_answer(question, references):
        return "answer"

    monkeypatch.setattr(tag_ask_routes, "get_tag_or_404", fake_get_tag_or_404)
    monkeypatch.setattr(tag_ask_routes, "_semantic_search_tag_scope", lambda **kwargs: {"tags": [], "documents": [], "comments": []})
    monkeypatch.setattr(tag_ask_routes, "generate_answer_from_references", fake_answer)
    monkeypatch.setattr(tag_ask_routes, "parse_semantic_citations", lambda answer: ([], [], []))

    import asyncio

    result = asyncio.run(
        tag_ask_routes.ask_tags(
            payload=TagAskMultiRequest(question="pump", tag_ids=[1, 2]),
            db=db,
            current_user=current_user,
        )
    )

    assert result.answer == "answer"
    assert calls == [(1, current_user), (2, current_user)]
