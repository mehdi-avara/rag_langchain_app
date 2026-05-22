import os
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

from routs import documents as document_routes


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.download_payloads = []

    def create_download_url(self, **kwargs):
        self.download_payloads.append(kwargs)
        return f"http://storage.local/{kwargs['disposition']}"


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_doc(doc_id=10, asset_id=99):
    return SimpleNamespace(
        id=doc_id,
        owner_id=3,
        original_asset_id=asset_id,
    )


@pytest.mark.asyncio
async def test_document_download_url_uses_attachment_by_default(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id))
    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(document_routes.settings, "S3_DOWNLOAD_EXPIRES_SECONDS", 300)

    result = await document_routes.create_document_download_url(
        doc_id=10,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 99
    assert result["download_url"] == "http://storage.local/attachment"
    assert result["expires_seconds"] == 300
    assert manager.download_payloads[0]["asset_id"] == 99
    assert manager.download_payloads[0]["user"] is current_user
    assert manager.download_payloads[0]["disposition"] == "attachment"


@pytest.mark.asyncio
async def test_document_download_url_supports_inline_preview(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id))
    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(document_routes.settings, "S3_DOWNLOAD_EXPIRES_SECONDS", 300)

    result = await document_routes.create_document_download_url(
        doc_id=10,
        disposition="inline",
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 99
    assert result["download_url"] == "http://storage.local/inline"
    assert manager.download_payloads[0]["disposition"] == "inline"


@pytest.mark.asyncio
async def test_document_download_url_rejects_document_without_asset(monkeypatch):
    db = object()
    current_user = make_user()

    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id, asset_id=None))

    with pytest.raises(HTTPException) as exc:
        await document_routes.create_document_download_url(
            doc_id=10,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "This document has no asset download URL"
