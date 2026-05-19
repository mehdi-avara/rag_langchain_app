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

from model_management.models import ModelDocumentLink
from model_management.routes import documents as model_document_routes
from model_management.schemas import ModelDocLinkCreate
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.target is ModelDocumentLink:
            return self.db.link_result
        return None


class FakeDB:
    def __init__(self, link_result=None):
        self.link_result = link_result
        self.added = []
        self.committed = False
        self.refreshed = []

    def query(self, target):
        return FakeQuery(self, target)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 19, 10, 0, 0)
        self.refreshed.append(obj)


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_model(model_id=8):
    return SimpleNamespace(id=model_id, company_id=1)


def make_doc(doc_id=45):
    return SimpleNamespace(id=doc_id, owner_id=3)


def make_link(model_id=8, document_id=45, user_id=3, note="old note"):
    return SimpleNamespace(
        model_id=model_id,
        document_id=document_id,
        linked_by_user_id=user_id,
        note=note,
        created_at=datetime(2026, 5, 19, 10, 0, 0),
    )


def test_model_document_upload_url_checks_model_and_delegates(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    calls = {}

    def fake_get_model_or_404(db_arg, model_id, current_user_arg):
        calls["model"] = (db_arg, model_id, current_user_arg)
        return make_model(model_id)

    def fake_create_document_upload_url(payload, db, current_user):
        calls["upload_url"] = (payload, db, current_user)
        return {
            "asset_id": 77,
            "upload_url": "http://storage.local/upload",
            "method": "PUT",
            "expires_seconds": 900,
            "headers": {"Content-Type": payload.content_type},
        }

    monkeypatch.setattr(model_document_routes, "get_model_or_404", fake_get_model_or_404)
    monkeypatch.setattr(model_document_routes, "create_document_upload_url", fake_create_document_upload_url)

    payload = AssetUploadUrlCreate(
        filename="manual.pdf",
        content_type="application/pdf",
        size_bytes=100,
        purpose="document",
    )

    result = model_document_routes.create_model_document_upload_url(
        model_id=8,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["method"] == "PUT"
    assert calls["model"] == (db, 8, current_user)
    assert calls["upload_url"] == (payload, db, current_user)


def test_model_document_complete_upload_links_created_document(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    calls = {}

    def fake_get_model_or_404(db_arg, model_id, current_user_arg):
        calls.setdefault("models", []).append((db_arg, model_id, current_user_arg))
        return make_model(model_id)

    def fake_complete_document_upload(asset_id, payload, db, current_user):
        calls["complete"] = (asset_id, payload, db, current_user)
        return {"doc_id": 45, "asset_id": asset_id, "status": "queued"}

    def fake_get_accessible_document(db_arg, document_id, current_user_arg, permission):
        calls["document"] = (db_arg, document_id, current_user_arg, permission)
        return make_doc(document_id)

    monkeypatch.setattr(model_document_routes, "get_model_or_404", fake_get_model_or_404)
    monkeypatch.setattr(model_document_routes, "complete_document_upload", fake_complete_document_upload)
    monkeypatch.setattr(model_document_routes, "_get_accessible_document", fake_get_accessible_document)

    payload = AssetCompleteUploadIn(checksum="checksum-1")

    result = model_document_routes.complete_model_document_upload_and_link(
        model_id=8,
        asset_id=77,
        payload=payload,
        link_description="linked by asset flow",
        db=db,
        current_user=current_user,
    )

    assert result.model_id == 8
    assert result.document_id == 45
    assert result.linked_by_user_id == 3
    assert result.note == "linked by asset flow"
    assert db.committed is True
    assert db.refreshed == [result]
    assert calls["models"] == [(db, 8, current_user), (db, 8, current_user)]
    assert calls["complete"] == (77, payload, db, current_user)
    assert calls["document"] == (db, 45, current_user, "read")


def test_model_document_complete_upload_accepts_object_result(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(model_document_routes, "get_model_or_404", lambda db, model_id, current_user: make_model(model_id))
    monkeypatch.setattr(
        model_document_routes,
        "complete_document_upload",
        lambda asset_id, payload, db, current_user: SimpleNamespace(doc_id=46, asset_id=asset_id),
    )
    monkeypatch.setattr(
        model_document_routes,
        "_get_accessible_document",
        lambda db, document_id, current_user, permission: make_doc(document_id),
    )

    result = model_document_routes.complete_model_document_upload_and_link(
        model_id=8,
        asset_id=78,
        payload=AssetCompleteUploadIn(),
        link_description=None,
        db=db,
        current_user=current_user,
    )

    assert result.model_id == 8
    assert result.document_id == 46
    assert result.note is None


def test_model_document_complete_upload_rejects_missing_doc_id(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(model_document_routes, "get_model_or_404", lambda db, model_id, current_user: make_model(model_id))
    monkeypatch.setattr(
        model_document_routes,
        "complete_document_upload",
        lambda asset_id, payload, db, current_user: {"asset_id": asset_id, "status": "queued"},
    )

    with pytest.raises(HTTPException) as exc:
        model_document_routes.complete_model_document_upload_and_link(
            model_id=8,
            asset_id=77,
            payload=AssetCompleteUploadIn(),
            link_description=None,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Document upload did not return doc_id"


def test_model_document_link_document_returns_existing_link(monkeypatch):
    existing_link = make_link()
    db = FakeDB(link_result=existing_link)
    current_user = make_user()

    monkeypatch.setattr(model_document_routes, "get_model_or_404", lambda db, model_id, current_user: make_model(model_id))
    monkeypatch.setattr(
        model_document_routes,
        "_get_accessible_document",
        lambda db, document_id, current_user, permission: make_doc(document_id),
    )

    result = model_document_routes.link_document(
        model_id=8,
        payload=ModelDocLinkCreate(document_id=45, note="new note"),
        db=db,
        current_user=current_user,
    )

    assert result is existing_link
    assert db.added == []
    assert db.committed is False
