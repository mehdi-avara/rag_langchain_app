import os
import asyncio
import importlib
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

model_ask_routes = importlib.import_module("model_management.routes.ask")
tag_ask_routes = importlib.import_module("tag_management.routes.ask")
model_schemas = importlib.import_module("model_management.schemas")
tag_schemas = importlib.import_module("tag_management.schemas")


def make_user(user_id=7, company_id=4):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user")


def test_ask_model_uses_scoped_semantic_search(monkeypatch):
    current_user = make_user()
    calls = []

    monkeypatch.setattr(
        model_ask_routes,
        "get_model_or_404",
        lambda db, model_id, current_user: SimpleNamespace(id=model_id),
    )

    def fake_scope(**kwargs):
        calls.append(kwargs)
        return {
            "models": [],
            "documents": [],
            "comments": [],
        }

    async def fake_generate(question, references):
        return "answer [chunk:101] [comment:202]"

    monkeypatch.setattr(model_ask_routes, "_semantic_search_model_scope", fake_scope)
    monkeypatch.setattr(model_ask_routes, "generate_answer_from_references", fake_generate)

    payload = model_schemas.ModelAskRequest(
        question="question",
        scope="both",
        types=[],
    )

    result = asyncio.run(
        model_ask_routes.ask_model(
            model_id=10,
            payload=payload,
            db=object(),
            current_user=current_user,
        )
    )

    assert calls[0]["current_user"] is current_user
    assert calls[0]["model_ids"] == [10]
    assert calls[0]["doc_top_k"] > 0
    assert calls[0]["comment_top_k"] > 0
    assert result.used_chunk_ids == [101]
    assert result.used_comment_ids == [202]


def test_ask_models_validates_each_model_and_uses_scoped_semantic_search(monkeypatch):
    current_user = make_user()
    validated = []
    calls = []

    monkeypatch.setattr(model_ask_routes, "require_company", lambda current_user: current_user.company_id)

    def fake_get_model(db, model_id, current_user):
        validated.append(model_id)
        return SimpleNamespace(id=model_id)

    def fake_scope(**kwargs):
        calls.append(kwargs)
        return {"models": [], "documents": [], "comments": []}

    async def fake_generate(question, references):
        return "answer"

    monkeypatch.setattr(model_ask_routes, "get_model_or_404", fake_get_model)
    monkeypatch.setattr(model_ask_routes, "_semantic_search_model_scope", fake_scope)
    monkeypatch.setattr(model_ask_routes, "generate_answer_from_references", fake_generate)

    payload = model_schemas.ModelAskMultiRequest(
        question="question",
        model_ids=[10, 10, 11],
        scope="docs",
        types=[],
    )

    result = asyncio.run(
        model_ask_routes.ask_models(
            payload=payload,
            db=object(),
            current_user=current_user,
        )
    )

    assert validated == [10, 11]
    assert calls[0]["current_user"] is current_user
    assert calls[0]["model_ids"] == [10, 11]
    assert calls[0]["doc_top_k"] > 0
    assert calls[0]["comment_top_k"] == 0
    assert result.used_chunk_ids == []
    assert result.used_comment_ids == []


def test_ask_tag_uses_descendants_and_scoped_semantic_search(monkeypatch):
    current_user = make_user()
    calls = []

    monkeypatch.setattr(
        tag_ask_routes,
        "get_tag_or_404",
        lambda db, tag_id, current_user: SimpleNamespace(id=tag_id),
    )
    monkeypatch.setattr(
        tag_ask_routes,
        "get_descendant_tag_ids",
        lambda db, tag_id, current_user: [tag_id, 20, 21],
    )

    def fake_scope(**kwargs):
        calls.append(kwargs)
        return {
            "tags": [],
            "documents": [],
            "comments": [],
        }

    async def fake_generate(question, references):
        return "answer [chunk:301] [comment:402]"

    monkeypatch.setattr(tag_ask_routes, "_semantic_search_tag_scope", fake_scope)
    monkeypatch.setattr(tag_ask_routes, "generate_answer_from_references", fake_generate)

    payload = tag_schemas.TagAskRequest(
        question="question",
        scope="both",
        types=[],
    )

    result = asyncio.run(
        tag_ask_routes.ask_tag(
            tag_id=10,
            payload=payload,
            db=object(),
            current_user=current_user,
        )
    )

    assert calls[0]["current_user"] is current_user
    assert calls[0]["tag_ids"] == [10, 20, 21]
    assert calls[0]["doc_top_k"] > 0
    assert calls[0]["comment_top_k"] > 0
    assert result.used_chunk_ids == [301]
    assert result.used_comment_ids == [402]


def test_ask_tags_validates_each_tag_and_uses_scoped_semantic_search(monkeypatch):
    current_user = make_user()
    validated = []
    calls = []

    def fake_get_tag(db, tag_id, current_user):
        validated.append(tag_id)
        return SimpleNamespace(id=tag_id)

    def fake_scope(**kwargs):
        calls.append(kwargs)
        return {"tags": [], "documents": [], "comments": []}

    async def fake_generate(question, references):
        return "answer"

    monkeypatch.setattr(tag_ask_routes, "get_tag_or_404", fake_get_tag)
    monkeypatch.setattr(tag_ask_routes, "_semantic_search_tag_scope", fake_scope)
    monkeypatch.setattr(tag_ask_routes, "generate_answer_from_references", fake_generate)

    payload = tag_schemas.TagAskMultiRequest(
        question="question",
        tag_ids=[10, 10, 11],
        scope="comments",
        types=[],
    )

    result = asyncio.run(
        tag_ask_routes.ask_tags(
            payload=payload,
            db=object(),
            current_user=current_user,
        )
    )

    assert validated == [10, 11]
    assert calls[0]["current_user"] is current_user
    assert calls[0]["tag_ids"] == [10, 11]
    assert calls[0]["doc_top_k"] == 0
    assert calls[0]["comment_top_k"] > 0
    assert result.used_chunk_ids == []
    assert result.used_comment_ids == []
