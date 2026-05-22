import os
from pathlib import Path
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


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.download_payloads = []

    def download_asset_to_path(self, **kwargs):
        self.download_payloads.append(kwargs)
        Path(kwargs["target_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["target_path"]).write_bytes(b"%PDF fake pdf content")


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_doc(doc_id=10, file_path=None, asset_id=99):
    return SimpleNamespace(
        id=doc_id,
        owner_id=3,
        file_path=file_path,
        original_asset_id=asset_id,
    )


@pytest.mark.asyncio
async def test_stream_pdf_downloads_asset_to_local_cache_when_missing(monkeypatch, tmp_path):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(document_routes.settings, "files_dir", str(tmp_path))
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id=doc_id, file_path=None, asset_id=99))
    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)

    response = await document_routes.stream_pdf(
        request=FakeRequest(),
        doc_id=10,
        db=db,
        current_user=current_user,
    )

    assert response.status_code == 200
    assert (tmp_path / "10" / "original.pdf").exists()
    assert manager.download_payloads[0]["asset_id"] == 99
    assert manager.download_payloads[0]["user"] is current_user


@pytest.mark.asyncio
async def test_stream_pdf_supports_valid_range(monkeypatch, tmp_path):
    db = object()
    current_user = make_user()
    doc_dir = tmp_path / "custom-doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "original.pdf").write_bytes(b"0123456789")

    monkeypatch.setattr(document_routes.settings, "files_dir", str(tmp_path))
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id=doc_id, file_path="custom-doc", asset_id=None))

    response = await document_routes.stream_pdf(
        request=FakeRequest(headers={"range": "bytes=2-5"}),
        doc_id=10,
        db=db,
        current_user=current_user,
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"


@pytest.mark.asyncio
async def test_stream_pdf_rejects_invalid_range(monkeypatch, tmp_path):
    db = object()
    current_user = make_user()
    doc_dir = tmp_path / "custom-doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "original.pdf").write_bytes(b"0123456789")

    monkeypatch.setattr(document_routes.settings, "files_dir", str(tmp_path))
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id=doc_id, file_path="custom-doc", asset_id=None))

    with pytest.raises(HTTPException) as exc:
        await document_routes.stream_pdf(
            request=FakeRequest(headers={"range": "bytes=9-2"}),
            doc_id=10,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 416
    assert exc.value.detail == "Invalid range header"


@pytest.mark.asyncio
async def test_stream_pdf_returns_404_when_no_local_file_and_no_asset(monkeypatch, tmp_path):
    db = object()
    current_user = make_user()

    monkeypatch.setattr(document_routes.settings, "files_dir", str(tmp_path))
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda db, doc_id, user, action: make_doc(doc_id=doc_id, file_path=None, asset_id=None))

    with pytest.raises(HTTPException) as exc:
        await document_routes.stream_pdf(
            request=FakeRequest(),
            doc_id=10,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "File not found"
