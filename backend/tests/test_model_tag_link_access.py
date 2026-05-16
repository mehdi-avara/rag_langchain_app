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

from model_management.routes import documents as model_documents
from model_management.routes import comments as model_comments
from tag_management.routes import documents as tag_documents
from tag_management.routes import comments as tag_comments
from model_management.schemas import ModelDocLinkCreate, ModelCommentLinkCreate
from tag_management.schemas import TagDocLinkCreate, TagCommentLinkCreate


class FakeDB:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


def make_user(user_id=7, company_id=4):
    return SimpleNamespace(id=user_id, company_id=company_id)


def make_model(model_id=10):
    return SimpleNamespace(id=model_id)


def make_tag(tag_id=20):
    return SimpleNamespace(id=tag_id)


def make_doc(doc_id=30):
    return SimpleNamespace(
        id=doc_id,
        filename="doc.pdf",
        n_pages=1,
        n_chunks=2,
        created_at=datetime(2026, 5, 16, 10, 0, 0),
        status="DONE",
        abstract=None,
        file_path="/tmp/doc.pdf",
    )


def make_comment(comment_id=40, user_id=7):
    return SimpleNamespace(
        id=comment_id,
        user_id=user_id,
        title="comment",
        type="comment",
        content="content",
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def test_model_link_document_uses_accessible_document(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    model = make_model()
    doc = make_doc()
    calls = {}

    monkeypatch.setattr(model_documents, "get_model_or_404", lambda db, model_id, current_user: model)

    def fake_get_accessible_document(db, document_id, current_user, action):
        calls["document_id"] = document_id
        calls["user_id"] = current_user.id
        calls["action"] = action
        return doc

    monkeypatch.setattr(model_documents, "_get_accessible_document", fake_get_accessible_document)

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    db.query = lambda *_args: Query()

    result = model_documents.link_document(
        model_id=10,
        payload=ModelDocLinkCreate(document_id=30, note="note"),
        db=db,
        current_user=current_user,
    )

    assert calls == {"document_id": 30, "user_id": 7, "action": "read"}
    assert result.model_id == 10
    assert result.document_id == 30
    assert result.linked_by_user_id == 7
    assert db.committed is True


def test_model_link_document_rejects_inaccessible_document(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(model_documents, "get_model_or_404", lambda db, model_id, current_user: make_model())

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Document not found")

    monkeypatch.setattr(model_documents, "_get_accessible_document", deny)

    with pytest.raises(HTTPException) as exc:
        model_documents.link_document(
            model_id=10,
            payload=ModelDocLinkCreate(document_id=30),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert db.committed is False


def test_tag_link_document_uses_accessible_document_and_user_id(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    tag = make_tag()
    doc = make_doc()

    monkeypatch.setattr(tag_documents, "get_tag_or_404", lambda db, tag_id, current_user: tag)
    monkeypatch.setattr(tag_documents, "_get_accessible_document", lambda db, document_id, current_user, action: doc)

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    db.query = lambda *_args: Query()

    result = tag_documents.link_document(
        tag_id=20,
        payload=TagDocLinkCreate(document_id=30, start_page=1, end_page=2, note="note"),
        db=db,
        current_user=current_user,
    )

    assert result.tag_id == 20
    assert result.document_id == 30
    assert result.linked_by_user_id == 7
    assert not hasattr(result, "linked_by_company_id")
    assert db.committed is True


def test_tag_link_document_rejects_inaccessible_document(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(tag_documents, "get_tag_or_404", lambda db, tag_id, current_user: make_tag())

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Document not found")

    monkeypatch.setattr(tag_documents, "_get_accessible_document", deny)

    with pytest.raises(HTTPException) as exc:
        tag_documents.link_document(
            tag_id=20,
            payload=TagDocLinkCreate(document_id=30),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert db.committed is False


def test_model_link_comment_uses_owned_comment(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    model = make_model()
    comment = make_comment()
    calls = {}

    monkeypatch.setattr(model_comments, "get_model_or_404", lambda db, model_id, current_user: model)

    def fake_get_owned_comment(db, comment_id, current_user):
        calls["comment_id"] = comment_id
        calls["user_id"] = current_user.id
        return comment

    monkeypatch.setattr(model_comments, "_get_owned_comment", fake_get_owned_comment)

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    db.query = lambda *_args: Query()

    result = model_comments.link_comment(
        model_id=10,
        payload=ModelCommentLinkCreate(comment_id=40, note="note"),
        db=db,
        current_user=current_user,
    )

    assert calls == {"comment_id": 40, "user_id": 7}
    assert result.model_id == 10
    assert result.comment_id == 40
    assert result.linked_by_user_id == 7
    assert db.committed is True


def test_model_link_comment_rejects_unowned_comment(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(model_comments, "get_model_or_404", lambda db, model_id, current_user: make_model())

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Comment not found")

    monkeypatch.setattr(model_comments, "_get_owned_comment", deny)

    with pytest.raises(HTTPException) as exc:
        model_comments.link_comment(
            model_id=10,
            payload=ModelCommentLinkCreate(comment_id=40),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert db.committed is False


def test_tag_link_comment_uses_owned_comment_and_user_id(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    tag = make_tag()
    comment = make_comment()

    monkeypatch.setattr(tag_comments, "get_tag_or_404", lambda db, tag_id, current_user: tag)
    monkeypatch.setattr(tag_comments, "_get_owned_comment", lambda db, comment_id, current_user: comment)

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    db.query = lambda *_args: Query()

    result = tag_comments.link_comment(
        tag_id=20,
        payload=TagCommentLinkCreate(comment_id=40, note="note"),
        db=db,
        current_user=current_user,
    )

    assert result.tag_id == 20
    assert result.comment_id == 40
    assert result.linked_by_user_id == 7
    assert not hasattr(result, "linked_by_company_id")
    assert db.committed is True


def test_tag_link_comment_rejects_unowned_comment(monkeypatch):
    db = FakeDB()
    current_user = make_user()

    monkeypatch.setattr(tag_comments, "get_tag_or_404", lambda db, tag_id, current_user: make_tag())

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Comment not found")

    monkeypatch.setattr(tag_comments, "_get_owned_comment", deny)

    with pytest.raises(HTTPException) as exc:
        tag_comments.link_comment(
            tag_id=20,
            payload=TagCommentLinkCreate(comment_id=40),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert db.committed is False
