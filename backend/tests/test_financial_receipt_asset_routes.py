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

from Models import FileAssetStatus
from financial_management.models import FinancialReceipt, FinancialReceiptFile
from financial_management.routes import files as financial_file_routes
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target
        self.ordered = False

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        self.ordered = True
        return self

    def first(self):
        if self.target is FinancialReceipt:
            return self.db.receipt_result
        if self.target is FinancialReceiptFile:
            return self.db.file_result
        return None

    def all(self):
        if self.target is FinancialReceiptFile:
            return self.db.file_rows
        return []


class FakeDB:
    def __init__(self, receipt_result=None, file_result=None, file_rows=None):
        self.receipt_result = receipt_result
        self.file_result = file_result
        self.file_rows = file_rows or []
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
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 19, 10, 0, 0)
        self.refreshed.append(obj)


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.created_payloads = []
        self.completed_payloads = []
        self.download_url_payloads = []
        self.deleted_payloads = []

    def create_upload_url(self, **kwargs):
        self.created_payloads.append(kwargs)
        return {
            "asset_id": 88,
            "upload_url": "http://storage.local/upload",
            "method": "PUT",
            "expires_seconds": 900,
            "headers": {"Content-Type": kwargs["content_type"]},
        }

    def complete_upload(self, **kwargs):
        self.completed_payloads.append(kwargs)
        return SimpleNamespace(
            id=88,
            company_id=1,
            original_filename="receipt-asset.pdf",
            content_type="application/pdf",
            storage_key="companies/1/assets/88/original",
            status=FileAssetStatus.READY.value,
        )

    def create_download_url(self, **kwargs):
        self.download_url_payloads.append(kwargs)
        return "http://storage.local/download"

    def delete_file(self, **kwargs):
        self.deleted_payloads.append(kwargs)


def make_user(user_id=3, company_id=1, role="user"):
    return SimpleNamespace(id=user_id, company_id=company_id, role=role, roles=[])


def make_receipt(receipt_id=10, company_id=1, owner_id=3):
    return SimpleNamespace(
        id=receipt_id,
        company_id=company_id,
        owner_id=owner_id,
        description="receipt",
        created_at=datetime(2026, 5, 19, 10, 0, 0),
    )


def make_file(file_id=20, receipt_id=10, user_id=3, asset_id=88):
    return SimpleNamespace(
        id=file_id,
        user_id=user_id,
        receipt_id=receipt_id,
        asset_id=asset_id,
        file_name="receipt-asset.pdf",
        media_address="companies/1/assets/88/original",
        content_type="application/pdf",
        created_at=datetime(2026, 5, 19, 10, 0, 0),
    )


def test_receipt_file_upload_url_uses_asset_manager(monkeypatch):
    db = FakeDB(receipt_result=make_receipt())
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(financial_file_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="receipt.pdf",
        content_type="application/pdf",
        size_bytes=120,
        purpose="receipt",
    )

    result = financial_file_routes.create_receipt_file_upload_url(
        receipt_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 88
    assert result["method"] == "PUT"
    assert manager.created_payloads[0]["filename"] == "receipt.pdf"
    assert manager.created_payloads[0]["purpose"] == "financial_receipt:10"
    assert manager.created_payloads[0]["owner"] is current_user


def test_receipt_file_complete_upload_creates_record(monkeypatch):
    db = FakeDB(receipt_result=make_receipt(), file_result=None)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(financial_file_routes, "StorageManager", lambda db_arg: manager)

    result = financial_file_routes.complete_receipt_file_upload(
        receipt_id=10,
        asset_id=88,
        payload=AssetCompleteUploadIn(),
        db=db,
        current_user=current_user,
    )

    assert result.id == 100
    assert result.asset_id == 88
    assert result.file_name == "receipt-asset.pdf"
    assert result.media_address == "companies/1/assets/88/original"
    assert result.content_type == "application/pdf"
    assert db.committed is True
    assert db.refreshed == [db.added[0]]


def test_receipt_file_complete_upload_rejects_cross_company_asset(monkeypatch):
    db = FakeDB(receipt_result=make_receipt(company_id=2), file_result=None)
    current_user = make_user(company_id=2)
    manager = FakeStorageManager(db)

    monkeypatch.setattr(financial_file_routes, "StorageManager", lambda db_arg: manager)

    with pytest.raises(HTTPException) as exc:
        financial_file_routes.complete_receipt_file_upload(
            receipt_id=10,
            asset_id=88,
            payload=AssetCompleteUploadIn(),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Asset not found"


def test_receipt_file_download_url_uses_asset_manager(monkeypatch):
    file_rec = make_file()
    db = FakeDB(receipt_result=make_receipt(), file_result=file_rec)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(financial_file_routes, "StorageManager", lambda db_arg: manager)

    result = financial_file_routes.create_receipt_file_download_url(
        receipt_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 88
    assert result["download_url"] == "http://storage.local/download"
    assert manager.download_url_payloads[0]["asset_id"] == 88
    assert manager.download_url_payloads[0]["user"] is current_user


def test_receipt_file_download_url_rejects_local_file_without_asset():
    file_rec = SimpleNamespace(
        id=20,
        user_id=3,
        receipt_id=10,
        file_name="old-local.pdf",
        media_address="/tmp/old-local.pdf",
        content_type="application/pdf",
        created_at=datetime(2026, 5, 19, 10, 0, 0),
    )
    db = FakeDB(receipt_result=make_receipt(), file_result=file_rec)
    current_user = make_user()

    with pytest.raises(HTTPException) as exc:
        financial_file_routes.create_receipt_file_download_url(
            receipt_id=10,
            file_id=20,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 409


def test_receipt_file_delete_asset_file_uses_asset_manager(monkeypatch):
    file_rec = make_file()
    db = FakeDB(receipt_result=make_receipt(), file_result=file_rec)
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(financial_file_routes, "StorageManager", lambda db_arg: manager)

    result = financial_file_routes.delete_receipt_file(
        receipt_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert manager.deleted_payloads[0]["asset_id"] == 88
    assert manager.deleted_payloads[0]["user"] is current_user
    assert manager.deleted_payloads[0]["hard_delete"] is False
    assert db.deleted == [file_rec]
    assert db.committed is True
