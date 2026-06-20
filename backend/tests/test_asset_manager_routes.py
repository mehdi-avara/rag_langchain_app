import os
import sys
import types
from datetime import datetime
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

from Models import Comment, CommentFile, Document, FileAssetStatus
from routs import documents as document_routes
from routs.comments import files as comment_file_routes
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target
        self.ordered = False

    def join(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        self.ordered = True
        return self

    def first(self):
        if self.target is Comment:
            return self.db.comment_result
        if self.target is CommentFile:
            return self.db.comment_file_result
        if self.target is Document:
            return self.db.document_result
        return None

    def all(self):
        if self.target is CommentFile:
            return self.db.comment_file_rows
        if self.target is Document:
            return self.db.document_rows
        return []


class FakeDB:
    def __init__(
        self,
        comment_result=None,
        comment_file_result=None,
        comment_file_rows=None,
        document_result=None,
        document_rows=None,
    ):
        self.comment_result = comment_result
        self.comment_file_result = comment_file_result
        self.comment_file_rows = comment_file_rows or []
        self.document_result = document_result
        self.document_rows = document_rows or []
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
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.created_payloads = []
        self.completed_payloads = []
        self.download_url_payloads = []
        self.download_to_path_payloads = []
        self.deleted_payloads = []

    def create_upload_url(self, **kwargs):
        self.created_payloads.append(kwargs)
        return {
            "asset_id": 77,
            "upload_url": "http://storage.local/upload",
            "method": "PUT",
            "expires_seconds": 900,
            "headers": {"Content-Type": kwargs["content_type"]},
        }

    def complete_upload(self, **kwargs):
        self.completed_payloads.append(kwargs)
        return SimpleNamespace(
            id=77,
            original_filename="asset-test.pdf",
            content_type="application/pdf",
            storage_key="companies/1/assets/77/original",
            status=FileAssetStatus.READY.value,
        )

    def create_download_url(self, **kwargs):
        self.download_url_payloads.append(kwargs)
        return "http://storage.local/download"

    def download_asset_to_path(self, **kwargs):
        self.download_to_path_payloads.append(kwargs)
        target = Path(kwargs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.7\nasset pdf\n")
        return SimpleNamespace(
            id=kwargs["asset_id"],
            original_filename="asset-test.pdf",
            content_type="application/pdf",
            storage_key="companies/1/assets/77/original",
            status=FileAssetStatus.READY.value,
        )

    def delete_file(self, **kwargs):
        self.deleted_payloads.append(kwargs)


def make_user(user_id=3, company_id=1, role="user"):
    return SimpleNamespace(id=user_id, company_id=company_id, role=role, roles=[])


def make_comment(comment_id=10, user_id=3):
    return SimpleNamespace(
        id=comment_id,
        user_id=user_id,
        title="Title",
        content="Content",
        type="comment",
        created_at=datetime(2026, 5, 19, 10, 0, 0),
        files=[],
    )


def make_comment_file(file_id=20, user_id=3, comment_id=10, asset_id=77):
    return SimpleNamespace(
        id=file_id,
        user_id=user_id,
        comment_id=comment_id,
        asset_id=asset_id,
        file_name="asset-test.pdf",
        media_address="companies/1/assets/77/original",
    )


def make_document(doc_id=45, owner_id=3, original_asset_id=77):
    return SimpleNamespace(
        id=doc_id,
        owner_id=owner_id,
        original_asset_id=original_asset_id,
        filename="asset-test.pdf",
        n_pages=0,
        n_chunks=0,
        status="queued",
        abstract=None,
        file_path=str(doc_id),
        created_at=datetime(2026, 5, 19, 10, 0, 0),
    )


def test_comment_file_upload_url_uses_asset_manager(monkeypatch):
    db = FakeDB(comment_result=make_comment())
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(comment_file_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="comment-file.txt",
        content_type="text/plain",
        size_bytes=12,
        purpose="comment",
    )

    result = comment_file_routes.create_comment_file_upload_url(
        comment_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["method"] == "PUT"
    assert manager.created_payloads[0]["filename"] == "comment-file.txt"
    assert manager.created_payloads[0]["purpose"] == "comment:10"
    assert manager.created_payloads[0]["owner"] is current_user


def test_comment_file_complete_upload_creates_comment_file(monkeypatch):
    db = FakeDB(comment_result=make_comment(), comment_file_result=None)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(comment_file_routes, "StorageManager", lambda db_arg: manager)

    result = comment_file_routes.complete_comment_file_upload(
        comment_id=10,
        asset_id=77,
        payload=AssetCompleteUploadIn(),
        db=db,
        current_user=current_user,
    )

    assert result.user_id == 3
    assert result.comment_id == 10
    assert result.asset_id == 77
    assert result.file_name == "asset-test.pdf"
    assert result.media_address == "companies/1/assets/77/original"
    assert db.committed is True
    assert db.refreshed == [result]


def test_comment_file_download_url_uses_asset_manager(monkeypatch):
    file_rec = make_comment_file()
    db = FakeDB(comment_result=make_comment(), comment_file_result=file_rec)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(comment_file_routes, "StorageManager", lambda db_arg: manager)

    result = comment_file_routes.create_comment_file_download_url(
        comment_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["download_url"] == "http://storage.local/download"
    assert manager.download_url_payloads[0]["asset_id"] == 77
    assert manager.download_url_payloads[0]["user"] is current_user


def test_document_upload_url_rejects_non_pdf():
    db = FakeDB()
    current_user = make_user()

    payload = AssetUploadUrlCreate(
        filename="note.txt",
        content_type="text/plain",
        size_bytes=10,
        purpose="document",
    )

    with pytest.raises(HTTPException) as exc:
        document_routes.create_document_upload_url(
            payload=payload,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 415
    assert exc.value.detail == "Only PDF documents are supported"


def test_document_upload_url_uses_asset_manager(monkeypatch):
    db = FakeDB()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="document.pdf",
        content_type="application/pdf",
        size_bytes=100,
        purpose="document",
    )

    result = document_routes.create_document_upload_url(
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["headers"]["Content-Type"] == "application/pdf"
    assert manager.created_payloads[0]["purpose"] == "document_original_pdf"
    assert manager.created_payloads[0]["owner"] is current_user


def test_document_complete_upload_creates_document_and_local_pdf(tmp_path, monkeypatch):
    db = FakeDB()
    current_user = make_user()
    manager = FakeStorageManager(db)

    queued = {}

    fake_tasks = types.ModuleType("core.celery.tasks")

    class FakeMineruTask:
        @staticmethod
        def delay(
            doc_id,
            pdf_path=None,
            asset_id=None,
            owner_id=None,
            document_version_id=None,
        ):
            queued["doc_id"] = doc_id
            queued["pdf_path"] = pdf_path
            queued["asset_id"] = asset_id
            queued["owner_id"] = owner_id
            queued["document_version_id"] = document_version_id

    fake_tasks.mineru_process_pdf = FakeMineruTask()
    monkeypatch.setitem(sys.modules, "core.celery.tasks", fake_tasks)
    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(document_routes.settings, "files_dir", str(tmp_path))

    result = document_routes.complete_document_upload(
        asset_id=77,
        payload=AssetCompleteUploadIn(),
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["status"] == "queued"
    assert result["doc_id"] == 100

    doc = db.added[0]
    assert doc.owner_id == 3
    assert doc.original_asset_id == 77
    assert doc.filename == "asset-test.pdf"
    assert doc.status == "queued"

    original_pdf = tmp_path / "100" / "original.pdf"
    assert original_pdf.exists()
    assert original_pdf.read_bytes().startswith(b"%PDF")
    assert queued == {
        "doc_id": 100,
        "pdf_path": None,
        "asset_id": 77,
        "owner_id": 3,
        "document_version_id": 101,
    }


@pytest.mark.asyncio
async def test_document_download_url_uses_original_asset(monkeypatch):
    doc = make_document()
    db = FakeDB(document_result=doc)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(document_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(document_routes, "_get_accessible_document", lambda *_args, **_kwargs: doc)

    result = await document_routes.create_document_download_url(
        doc_id=45,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 77
    assert result["download_url"] == "http://storage.local/download"
    assert manager.download_url_payloads[0]["asset_id"] == 77
    assert manager.download_url_payloads[0]["user"] is current_user
