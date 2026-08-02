import os
from types import SimpleNamespace
from datetime import datetime

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

from Models import Document, UserDocumentAccess
from routs import documents as document_routes


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def join(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self.target is Document:
            return self.db.document_result

        if self.target is UserDocumentAccess:
            return self.db.access_result

        return None

    def all(self):
        key = getattr(self.target, "key", "")

        if key == "id":
            return [(doc_id,) for doc_id in self.db.owned_ids]

        if key == "document_id":
            return [(doc_id,) for doc_id in self.db.granted_ids]

        if self.target is UserDocumentAccess:
            return self.db.access_rows

        return []


class FakeDB:
    def __init__(
        self,
        document_result=None,
        access_result=None,
        owned_ids=None,
        granted_ids=None,
        access_rows=None,
    ):
        self.document_result = document_result
        self.access_result = access_result
        self.owned_ids = owned_ids or []
        self.granted_ids = granted_ids or []
        self.access_rows = access_rows or []

    def query(self, target):
        return FakeQuery(self, target)


def make_role(
    name="user",
    is_active=True,
    company_id=1,
    is_system=False,
):
    return SimpleNamespace(
        name=name,
        is_active=is_active,
        company_id=company_id,
        is_system=is_system,
    )


def make_user(user_id=3, company_id=1, role="user", roles=None):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        role=role,
        roles=roles if roles is not None else [],
    )


def make_doc(doc_id=10, owner_id=3):
    return SimpleNamespace(
        id=doc_id,
        owner_id=owner_id,
        filename="document.pdf",
        n_pages=1,
        n_chunks=1,
        status="done",
        abstract=None,
        file_path="10",
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def make_access(
    user_id=4,
    document_id=10,
    can_read=True,
    can_download=False,
    can_ask=True,
    can_update=False,
    can_delete=False,
):
    return SimpleNamespace(
        id=1,
        user_id=user_id,
        document_id=document_id,
        can_read=can_read,
        can_download=can_download,
        can_ask=can_ask,
        can_update=can_update,
        can_delete=can_delete,
        granted_by_user_id=3,
        created_at=datetime(2026, 5, 16, 10, 0, 0),
        updated_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def test_is_company_admin_rejects_legacy_role_string():
    user = make_user(role="admin")

    assert document_routes._is_company_admin(user) is False


def test_is_company_admin_allows_matching_tenant_role():
    user = make_user(
        role="company_admin",
        roles=[
            make_role(
                "company_admin",
                True,
                company_id=1,
                is_system=False,
            )
        ],
    )

    assert document_routes._is_company_admin(user) is True


def test_is_company_admin_rejects_foreign_tenant_role():
    user = make_user(
        company_id=1,
        role="company_admin",
        roles=[
            make_role(
                "company_admin",
                True,
                company_id=2,
                is_system=False,
            )
        ],
    )

    assert document_routes._is_company_admin(user) is False


def test_is_company_admin_rejects_inactive_tenant_role():
    user = make_user(
        role="company_admin",
        roles=[
            make_role(
                "company_admin",
                False,
                company_id=1,
                is_system=False,
            )
        ],
    )

    assert document_routes._is_company_admin(user) is False


def test_is_company_admin_allows_platform_admin_role():
    user = make_user(
        role="admin",
        roles=[
            make_role(
                "admin",
                True,
                company_id=None,
                is_system=True,
            )
        ],
    )

    assert document_routes._is_company_admin(user) is True


def test_get_company_document_returns_document_when_found():
    doc = make_doc()
    db = FakeDB(document_result=doc)
    user = make_user(company_id=1)

    result = document_routes._get_company_document(db, doc_id=10, current_user=user)

    assert result is doc


def test_get_company_document_rejects_user_without_company():
    db = FakeDB(document_result=make_doc())
    user = make_user(company_id=None)

    with pytest.raises(HTTPException) as exc:
        document_routes._get_company_document(db, doc_id=10, current_user=user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "User has no company"


def test_get_company_document_raises_404_when_not_found_or_cross_company():
    db = FakeDB(document_result=None)
    user = make_user(company_id=1)

    with pytest.raises(HTTPException) as exc:
        document_routes._get_company_document(db, doc_id=10, current_user=user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found"


def test_has_document_access_allows_owner_for_all_actions():
    doc = make_doc(owner_id=3)
    db = FakeDB(access_result=None)
    user = make_user(user_id=3, role="user")

    for action in ["read", "download", "ask", "update", "delete"]:
        assert document_routes._has_document_access(db, doc, user, action) is True


def test_has_document_access_allows_company_admin_for_all_actions():
    doc = make_doc(owner_id=4)
    db = FakeDB(access_result=None)
    user = make_user(
        user_id=3,
        role="company_admin",
        roles=[
            make_role(
                "company_admin",
                company_id=1,
                is_system=False,
            )
        ],
    )

    for action in ["read", "download", "ask", "update", "delete"]:
        assert document_routes._has_document_access(db, doc, user, action) is True


def test_has_document_access_denies_when_no_grant_exists():
    doc = make_doc(owner_id=3)
    db = FakeDB(access_result=None)
    user = make_user(user_id=4, role="user")

    assert document_routes._has_document_access(db, doc, user, "read") is False


def test_has_document_access_uses_grant_flags():
    doc = make_doc(owner_id=3)
    user = make_user(user_id=4, role="user")
    access = make_access(
        user_id=4,
        document_id=10,
        can_read=True,
        can_download=False,
        can_ask=True,
        can_update=False,
        can_delete=True,
    )
    db = FakeDB(access_result=access)

    assert document_routes._has_document_access(db, doc, user, "read") is True
    assert document_routes._has_document_access(db, doc, user, "download") is False
    assert document_routes._has_document_access(db, doc, user, "ask") is True
    assert document_routes._has_document_access(db, doc, user, "update") is False
    assert document_routes._has_document_access(db, doc, user, "delete") is True


def test_has_document_access_rejects_unknown_action():
    doc = make_doc(owner_id=3)
    user = make_user(user_id=4, role="user")
    db = FakeDB(access_result=make_access())

    assert document_routes._has_document_access(db, doc, user, "unknown") is False


def test_get_accessible_document_returns_document_when_allowed():
    doc = make_doc(owner_id=3)
    db = FakeDB(document_result=doc)
    user = make_user(user_id=3, company_id=1)

    result = document_routes._get_accessible_document(db, doc_id=10, current_user=user, action="read")

    assert result is doc


def test_get_accessible_document_raises_404_when_not_allowed():
    doc = make_doc(owner_id=3)
    db = FakeDB(document_result=doc, access_result=None)
    user = make_user(user_id=4, company_id=1, role="user")

    with pytest.raises(HTTPException) as exc:
        document_routes._get_accessible_document(db, doc_id=10, current_user=user, action="read")

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found"


def test_get_accessible_document_ids_returns_none_for_company_admin():
    db = FakeDB(owned_ids=[1], granted_ids=[2])
    user = make_user(
        user_id=4,
        company_id=1,
        role="company_admin",
        roles=[
            make_role(
                "company_admin",
                company_id=1,
                is_system=False,
            )
        ],
    )

    result = document_routes._get_accessible_document_ids(db, current_user=user, action="read")

    assert result is None


def test_get_accessible_document_ids_rejects_user_without_company():
    db = FakeDB(owned_ids=[1], granted_ids=[2])
    user = make_user(user_id=4, company_id=None, role="user")

    with pytest.raises(HTTPException) as exc:
        document_routes._get_accessible_document_ids(db, current_user=user, action="read")

    assert exc.value.status_code == 403
    assert exc.value.detail == "User has no company"


def test_get_accessible_document_ids_returns_owned_and_granted_without_duplicates():
    db = FakeDB(owned_ids=[1, 2], granted_ids=[2, 3])
    user = make_user(user_id=4, company_id=1, role="user")

    result = document_routes._get_accessible_document_ids(db, current_user=user, action="read")

    assert result == [1, 2, 3]


def test_get_accessible_document_ids_returns_empty_for_unknown_action():
    db = FakeDB(owned_ids=[1, 2], granted_ids=[3])
    user = make_user(user_id=4, company_id=1, role="user")

    result = document_routes._get_accessible_document_ids(db, current_user=user, action="unknown")

    assert result == []
