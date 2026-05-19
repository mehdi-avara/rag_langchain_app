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

from Models import FileAssetStatus, User
from routs import users as user_routes
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.target is User:
            return self.db.user_result
        return None


class FakeDB:
    def __init__(self, user_result=None):
        self.user_result = user_result
        self.committed = False
        self.refreshed = []
        self.queries = []

    def query(self, target):
        query = FakeQuery(self, target)
        self.queries.append(query)
        return query

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


class FakeStorageManager:
    def __init__(self, db, asset=None):
        self.db = db
        self.asset = asset or make_asset()
        self.created_payloads = []
        self.completed_payloads = []
        self.download_payloads = []

    def create_upload_url(self, **kwargs):
        self.created_payloads.append(kwargs)
        return {
            "asset_id": 90,
            "upload_url": "http://storage.local/upload",
            "method": "PUT",
            "expires_seconds": 900,
            "headers": {"Content-Type": kwargs["content_type"]},
        }

    def complete_upload(self, **kwargs):
        self.completed_payloads.append(kwargs)
        return self.asset

    def create_download_url(self, **kwargs):
        self.download_payloads.append(kwargs)
        return "http://storage.local/download"


def make_user(user_id=3, company_id=1, role="user", profile_asset_id=None):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        username="user@example.com",
        role=role,
        First_name="Test",
        Last_name="User",
        image_path=None,
        profile_asset_id=profile_asset_id,
        roles=[],
    )


def make_asset(
    asset_id=90,
    content_type="image/png",
    status=FileAssetStatus.READY.value,
):
    return SimpleNamespace(
        id=asset_id,
        original_filename="profile-test.png",
        content_type=content_type,
        storage_key=f"companies/1/assets/{asset_id}/original",
        status=status,
    )


def test_profile_image_upload_url_uses_asset_manager(monkeypatch):
    user = make_user()
    db = FakeDB(user_result=user)
    current_user = user
    manager = FakeStorageManager(db)

    monkeypatch.setattr(user_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="profile-test.png",
        content_type="image/png",
        size_bytes=12,
        purpose="profile",
    )

    result = user_routes.create_profile_image_upload_url(
        payload=payload,
        current_user=current_user,
        db=db,
    )

    assert result["asset_id"] == 90
    assert result["method"] == "PUT"
    assert result["headers"]["Content-Type"] == "image/png"
    assert manager.created_payloads[0]["filename"] == "profile-test.png"
    assert manager.created_payloads[0]["content_type"] == "image/png"
    assert manager.created_payloads[0]["size_bytes"] == 12
    assert manager.created_payloads[0]["owner"] is current_user
    assert manager.created_payloads[0]["purpose"] == "profile_image:3"


def test_profile_image_upload_url_rejects_invalid_content_type():
    user = make_user()
    db = FakeDB(user_result=user)

    payload = AssetUploadUrlCreate(
        filename="profile-test.pdf",
        content_type="application/pdf",
        size_bytes=12,
        purpose="profile",
    )

    with pytest.raises(HTTPException) as exc:
        user_routes.create_profile_image_upload_url(
            payload=payload,
            current_user=user,
            db=db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported file type. Allowed: jpeg, png, gif, webp"


def test_profile_image_complete_upload_updates_user_and_returns_download_url(monkeypatch):
    user = make_user()
    db = FakeDB(user_result=user)
    current_user = user
    asset = make_asset(asset_id=91)
    manager = FakeStorageManager(db, asset=asset)

    monkeypatch.setattr(user_routes, "StorageManager", lambda db_arg: manager)

    result = user_routes.complete_profile_image_upload(
        asset_id=91,
        payload=AssetCompleteUploadIn(),
        current_user=current_user,
        db=db,
    )

    assert result.image_path == "companies/1/assets/91/original"
    assert result.profile_asset_id == 91
    assert result.download_url == "http://storage.local/download"
    assert user.profile_asset_id == 91
    assert user.image_path == "companies/1/assets/91/original"
    assert db.committed is True
    assert db.refreshed == [user]
    assert manager.completed_payloads[0]["asset_id"] == 91
    assert manager.completed_payloads[0]["user"] is current_user
    assert manager.download_payloads[0]["asset_id"] == 91
    assert manager.download_payloads[0]["user"] is current_user
    assert manager.download_payloads[0]["disposition"] == "inline"


def test_profile_image_complete_upload_rejects_non_image_asset(monkeypatch):
    user = make_user()
    db = FakeDB(user_result=user)
    asset = make_asset(asset_id=92, content_type="application/pdf")
    manager = FakeStorageManager(db, asset=asset)

    monkeypatch.setattr(user_routes, "StorageManager", lambda db_arg: manager)

    with pytest.raises(HTTPException) as exc:
        user_routes.complete_profile_image_upload(
            asset_id=92,
            payload=AssetCompleteUploadIn(),
            current_user=user,
            db=db,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported file type. Allowed: jpeg, png, gif, webp"


def test_profile_image_complete_upload_rejects_not_ready_asset(monkeypatch):
    user = make_user()
    db = FakeDB(user_result=user)
    asset = make_asset(asset_id=93, status=FileAssetStatus.PENDING.value)
    manager = FakeStorageManager(db, asset=asset)

    monkeypatch.setattr(user_routes, "StorageManager", lambda db_arg: manager)

    with pytest.raises(HTTPException) as exc:
        user_routes.complete_profile_image_upload(
            asset_id=93,
            payload=AssetCompleteUploadIn(),
            current_user=user,
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Asset is not ready"


def test_profile_image_download_url_uses_asset_manager(monkeypatch):
    user = make_user(profile_asset_id=94)
    db = FakeDB(user_result=user)
    manager = FakeStorageManager(db)

    monkeypatch.setattr(user_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(user_routes.settings, "S3_DOWNLOAD_EXPIRES_SECONDS", 300)

    result = user_routes.create_profile_image_download_url(
        current_user=user,
        db=db,
    )

    assert result["asset_id"] == 94
    assert result["download_url"] == "http://storage.local/download"
    assert result["expires_seconds"] == 300
    assert manager.download_payloads[0]["asset_id"] == 94
    assert manager.download_payloads[0]["user"] is user
    assert manager.download_payloads[0]["disposition"] == "inline"


def test_profile_image_download_url_rejects_missing_asset():
    user = make_user(profile_asset_id=None)
    db = FakeDB(user_result=user)

    with pytest.raises(HTTPException) as exc:
        user_routes.create_profile_image_download_url(
            current_user=user,
            db=db,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "No profile image asset set"
