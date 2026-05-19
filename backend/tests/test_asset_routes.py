import os
from datetime import datetime
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

from routs import assets as asset_routes
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.created_payloads = []
        self.completed_payloads = []
        self.get_payloads = []
        self.download_payloads = []
        self.delete_payloads = []

    def create_upload_url(self, **kwargs):
        self.created_payloads.append(kwargs)
        return {
            "asset_id": 10,
            "upload_url": "http://storage.local/upload",
            "method": "PUT",
            "expires_seconds": 900,
            "headers": {"Content-Type": kwargs["content_type"]},
        }

    def complete_upload(self, **kwargs):
        self.completed_payloads.append(kwargs)
        return make_asset(asset_id=kwargs["asset_id"], status="ready")

    def get_asset(self, **kwargs):
        self.get_payloads.append(kwargs)
        return make_asset(asset_id=kwargs["asset_id"], status="ready")

    def create_download_url(self, **kwargs):
        self.download_payloads.append(kwargs)
        return "http://storage.local/download"

    def delete_file(self, **kwargs):
        self.delete_payloads.append(kwargs)


def make_user(user_id=3, company_id=1, role="user"):
    return SimpleNamespace(id=user_id, company_id=company_id, role=role, roles=[])


def make_asset(asset_id=10, status="pending"):
    return SimpleNamespace(
        id=asset_id,
        owner_id=3,
        company_id=1,
        original_filename="asset.pdf",
        content_type="application/pdf",
        size_bytes=120,
        checksum=None,
        bucket="porsa-assets",
        storage_backend="s3",
        status=status,
        purpose="test",
        created_at=datetime(2026, 5, 19, 10, 0, 0),
        updated_at=datetime(2026, 5, 19, 10, 0, 0),
        deleted_at=None,
    )


def test_create_asset_upload_url_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(asset_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="asset.pdf",
        content_type="application/pdf",
        size_bytes=120,
        purpose="test",
        checksum="abc",
    )

    result = asset_routes.create_asset_upload_url(
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 10
    assert result["method"] == "PUT"
    assert result["headers"]["Content-Type"] == "application/pdf"
    assert manager.created_payloads[0]["filename"] == "asset.pdf"
    assert manager.created_payloads[0]["content_type"] == "application/pdf"
    assert manager.created_payloads[0]["size_bytes"] == 120
    assert manager.created_payloads[0]["owner"] is current_user
    assert manager.created_payloads[0]["purpose"] == "test"
    assert manager.created_payloads[0]["checksum"] == "abc"


def test_complete_asset_upload_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(asset_routes, "StorageManager", lambda db_arg: manager)

    result = asset_routes.complete_asset_upload(
        asset_id=10,
        payload=AssetCompleteUploadIn(checksum="final-checksum"),
        db=db,
        current_user=current_user,
    )

    assert result.id == 10
    assert result.status == "ready"
    assert manager.completed_payloads[0]["asset_id"] == 10
    assert manager.completed_payloads[0]["user"] is current_user
    assert manager.completed_payloads[0]["checksum"] == "final-checksum"


def test_get_asset_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(asset_routes, "StorageManager", lambda db_arg: manager)

    result = asset_routes.get_asset(
        asset_id=10,
        db=db,
        current_user=current_user,
    )

    assert result.id == 10
    assert result.status == "ready"
    assert manager.get_payloads[0]["asset_id"] == 10
    assert manager.get_payloads[0]["user"] is current_user


def test_create_asset_download_url_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(asset_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(asset_routes.settings, "S3_DOWNLOAD_EXPIRES_SECONDS", 300)

    result = asset_routes.create_asset_download_url(
        asset_id=10,
        disposition="inline",
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 10
    assert result["download_url"] == "http://storage.local/download"
    assert result["expires_seconds"] == 300
    assert manager.download_payloads[0]["asset_id"] == 10
    assert manager.download_payloads[0]["user"] is current_user
    assert manager.download_payloads[0]["disposition"] == "inline"


def test_delete_asset_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(asset_routes, "StorageManager", lambda db_arg: manager)

    result = asset_routes.delete_asset(
        asset_id=10,
        hard_delete=True,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert manager.delete_payloads[0]["asset_id"] == 10
    assert manager.delete_payloads[0]["user"] is current_user
    assert manager.delete_payloads[0]["hard_delete"] is True
