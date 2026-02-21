import os

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

import sys
import types
import importlib

mineru_mod = types.ModuleType("mineru")
mineru_utils = types.ModuleType("mineru.utils")
mineru_cfg = types.ModuleType("mineru.utils.config_reader")
mineru_cfg.get_latex_delimiter_config = lambda: {}
sys.modules.setdefault("mineru", mineru_mod)
sys.modules.setdefault("mineru.utils", mineru_utils)
sys.modules.setdefault("mineru.utils.config_reader", mineru_cfg)

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import deps
from Models import CommentType
from db.init_db import get_db
from model_management.routes import model_router
from routs.comments import comment_router
from routs.documents import router as document_router
from tag_management.routes import tag_router

model_routes_module = importlib.import_module("model_management.routes.models")


class DummyQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class DummyDB:
    def __init__(self, tag_ids=None, model_ids=None):
        self.tag_ids = tag_ids or []
        self.model_ids = model_ids or []

    def query(self, *_args, **_kwargs):
        if self.tag_ids:
            return DummyQuery([(tag_id,) for tag_id in self.tag_ids])
        return DummyQuery([(model_id,) for model_id in self.model_ids])


def build_client(db):
    app = FastAPI()
    app.include_router(document_router, prefix="/documents")
    app.include_router(comment_router, prefix="/comments")
    app.include_router(tag_router)
    app.include_router(model_router)

    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id=7, role="admin")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_document_semantic_search_contract_and_top_k(monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "document_id": 10,
                "document_title": "Doc A",
                "part_id": 91,
                "part_text": "matched part",
            }
        ]

    monkeypatch.setattr("routs.documents.search_document_part_hits_semantic", fake_search)

    client = build_client(DummyDB())
    resp = client.post("/documents/semantic-search?top_k=1", json={"query": "q", "ids": [10], "limit": 99})
    assert resp.status_code == 200
    assert resp.json() == [{"document_id": 10, "document_title": "Doc A", "part_id": 91, "part_text": "matched part"}]
    assert captured["limit"] == 1


def test_comment_semantic_search_types_and_top_k(monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "comment_id": 30,
                "comment_title": "Failure note",
                "comment_content": "motor failure",
            }
        ]

    monkeypatch.setattr("routs.comments.comment.search_comment_hits_semantic", fake_search)

    client = build_client(DummyDB())
    resp = client.post(
        "/comments/semantic-search?top_k=2",
        json={"query": "motor", "ids": [30], "types": ["failure", "report"]},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["comment_id"] == 30
    assert captured["limit"] == 2
    assert captured["types"] == [CommentType.FAILURE, CommentType.REPORT]


def test_tag_semantic_search_includes_descendants_and_model_docs(monkeypatch):
    monkeypatch.setattr("tag_management.routes.tags.get_tag_or_404", lambda *args, **kwargs: SimpleNamespace(id=1))
    monkeypatch.setattr("tag_management.routes.tags.get_descendant_tag_ids", lambda *_args, **_kwargs: [1, 2])
    monkeypatch.setattr("tag_management.routes.tags.get_doc_ids_for_tags", lambda *_args, **_kwargs: [100])
    monkeypatch.setattr("tag_management.routes.tags.get_comment_ids_for_tags", lambda *_args, **_kwargs: [200])
    monkeypatch.setattr("tag_management.routes.tags.get_model_ids_for_tags", lambda *_args, **_kwargs: [500])
    monkeypatch.setattr("tag_management.routes.tags.get_model_document_ids", lambda *_args, **_kwargs: [101])
    monkeypatch.setattr("tag_management.routes.tags.get_tag_info_map", lambda *_args, **_kwargs: {1: SimpleNamespace(id=1, tag_name="Engine")})
    monkeypatch.setattr("tag_management.routes.tags.get_model_info_map", lambda *_args, **_kwargs: {500: SimpleNamespace(id=500, model="M-500")})
    monkeypatch.setattr("tag_management.routes.tags.get_doc_to_tag_map", lambda *_args, **_kwargs: {100: 1})
    monkeypatch.setattr("tag_management.routes.tags.get_comment_to_tag_map", lambda *_args, **_kwargs: {200: 1})
    monkeypatch.setattr("tag_management.routes.tags.get_doc_to_model_map", lambda *_args, **_kwargs: {101: 500})
    monkeypatch.setattr("tag_management.routes.tags.get_tag_to_model_map", lambda *_args, **_kwargs: {1: 500})

    monkeypatch.setattr(
        "tag_management.routes.tags.search_document_part_hits_semantic",
        lambda **_kwargs: [
            {"document_id": 100, "document_title": "Tag Doc", "part_id": 1, "part_text": "tag chunk"},
            {"document_id": 101, "document_title": "Model Doc", "part_id": 2, "part_text": "model chunk"},
        ],
    )
    monkeypatch.setattr(
        "tag_management.routes.tags.search_comment_hits_semantic",
        lambda **_kwargs: [{"comment_id": 200, "comment_title": "C", "comment_content": "text"}],
    )

    client = build_client(DummyDB(tag_ids=[1, 2]))
    resp = client.post(
        "/system_tags/1/semantic-search?top_k=3",
        json={"query": "engine", "types": ["comment", "failure"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["documents"]) == 2
    assert body["documents"][1]["model_id"] == 500
    assert body["documents"][1]["part_id"] == 2
    assert body["comments"][0]["tag_id"] == 1


def test_model_semantic_search_contract_top_k_and_types(monkeypatch):
    monkeypatch.setattr(model_routes_module, "get_model_or_404", lambda *_args, **_kwargs: SimpleNamespace(id=8))
    monkeypatch.setattr(model_routes_module, "get_doc_ids_for_models", lambda *_args, **_kwargs: [60])
    monkeypatch.setattr(model_routes_module, "get_comment_ids_for_models", lambda *_args, **_kwargs: [70])
    monkeypatch.setattr(model_routes_module, "get_model_info_map", lambda *_args, **_kwargs: {8: SimpleNamespace(id=8, model="MX")})
    monkeypatch.setattr(model_routes_module, "get_doc_to_model_map", lambda *_args, **_kwargs: {60: 8})
    monkeypatch.setattr(model_routes_module, "get_comment_to_model_map", lambda *_args, **_kwargs: {70: 8})
    monkeypatch.setattr(
        model_routes_module, "search_document_part_hits_semantic",
        lambda **_kwargs: [{"document_id": 60, "document_title": "Doc", "part_id": 9, "part_text": "chunk"}],
    )
    monkeypatch.setattr(
        model_routes_module, "search_comment_hits_semantic",
        lambda **_kwargs: [{"comment_id": 70, "comment_title": "R", "comment_content": "report text"}],
    )

    client = build_client(DummyDB(model_ids=[8]))
    resp = client.post("/models/8/semantic-search?top_k=1", json={"query": "x", "types": ["report"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["documents"][0] == {
        "model_id": 8,
        "model_title": "MX",
        "document_id": 60,
        "document_title": "Doc",
        "part_id": 9,
        "part_text": "chunk",
    }
    assert body["comments"][0]["comment_content"] == "report text"
