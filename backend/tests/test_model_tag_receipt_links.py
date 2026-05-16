import os
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

model_receipt_routes = importlib.import_module("model_management.routes.receipts")
tag_receipt_routes = importlib.import_module("tag_management.routes.receipts")


class FakeQuery:
    def __init__(self, result=None):
        self.result = result
        self.filters = []
        self.deleted = None

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def first(self):
        return self.result

    def order_by(self, *args):
        return self

    def all(self):
        return []


class FakeDB:
    def __init__(self, query_result=None):
        self.query_result = query_result
        self.added = None
        self.deleted = None
        self.committed = False
        self.refreshed = None

    def query(self, *args):
        return FakeQuery(self.query_result)

    def add(self, obj):
        self.added = obj

    def delete(self, obj):
        self.deleted = obj

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed = obj


def make_user(user_id=7, company_id=4):
    return SimpleNamespace(id=user_id, company_id=company_id)


def make_payload(receipt_id=55, note="note"):
    return SimpleNamespace(receipt_id=receipt_id, note=note)


def test_tag_link_receipt_sets_linked_by_user_id(monkeypatch):
    db = FakeDB(query_result=None)
    current_user = make_user()

    monkeypatch.setattr(tag_receipt_routes, "get_tag_or_404", lambda db, tag_id, current_user: SimpleNamespace(id=tag_id))
    monkeypatch.setattr(tag_receipt_routes, "get_receipt", lambda receipt_id, db, current_user: SimpleNamespace(id=receipt_id))
    monkeypatch.setattr(tag_receipt_routes, "safe_embed_link_note", lambda note: None)

    result = tag_receipt_routes.link_receipt(
        tag_id=10,
        payload=make_payload(receipt_id=55),
        db=db,
        current_user=current_user,
    )

    assert result is db.added
    assert db.added.tag_id == 10
    assert db.added.receipt_id == 55
    assert db.added.linked_by_user_id == 7
    assert not hasattr(db.added, "linked_by_company_id")
    assert db.committed is True


def test_model_unlink_receipt_checks_receipt_access_before_delete(monkeypatch):
    link = SimpleNamespace(model_id=10, receipt_id=55)
    db = FakeDB(query_result=link)
    current_user = make_user()
    calls = []

    monkeypatch.setattr(model_receipt_routes, "get_model_or_404", lambda db, model_id, current_user: SimpleNamespace(id=model_id))

    def fake_get_receipt(receipt_id, db, current_user):
        calls.append((receipt_id, current_user))
        return SimpleNamespace(id=receipt_id)

    monkeypatch.setattr(model_receipt_routes, "get_receipt", fake_get_receipt)

    result = model_receipt_routes.unlink_receipt(
        model_id=10,
        receipt_id=55,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert calls == [(55, current_user)]
    assert db.deleted is link
    assert db.committed is True


def test_tag_unlink_receipt_checks_receipt_access_before_delete(monkeypatch):
    link = SimpleNamespace(tag_id=10, receipt_id=55)
    db = FakeDB(query_result=link)
    current_user = make_user()
    calls = []

    monkeypatch.setattr(tag_receipt_routes, "get_tag_or_404", lambda db, tag_id, current_user: SimpleNamespace(id=tag_id))

    def fake_get_receipt(receipt_id, db, current_user):
        calls.append((receipt_id, current_user))
        return SimpleNamespace(id=receipt_id)

    monkeypatch.setattr(tag_receipt_routes, "get_receipt", fake_get_receipt)

    result = tag_receipt_routes.unlink_receipt(
        tag_id=10,
        receipt_id=55,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert calls == [(55, current_user)]
    assert db.deleted is link
    assert db.committed is True
