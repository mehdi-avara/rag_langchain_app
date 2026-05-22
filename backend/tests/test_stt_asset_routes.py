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

from routs import stt as stt_routes
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate


class FakeStorageManager:
    def __init__(self, db):
        self.db = db
        self.created_payloads = []
        self.completed_payloads = []
        self.download_payloads = []

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

    def download_asset_to_path(self, **kwargs):
        self.download_payloads.append(kwargs)
        kwargs["target_path"].write_bytes(b"audio-bytes")


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_asset(asset_id=10, status="pending"):
    return SimpleNamespace(
        id=asset_id,
        owner_id=3,
        company_id=1,
        original_filename="voice.mp3",
        content_type="audio/mpeg",
        size_bytes=120,
        checksum=None,
        bucket="porsa-assets",
        storage_backend="s3",
        status=status,
        purpose="stt_audio",
        created_at=datetime(2026, 5, 22, 10, 0, 0),
        updated_at=datetime(2026, 5, 22, 10, 0, 0),
        deleted_at=None,
    )


def test_create_audio_transcribe_upload_url_uses_storage_manager(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    monkeypatch.setattr(stt_routes, "StorageManager", lambda db_arg: manager)

    payload = AssetUploadUrlCreate(
        filename="voice.mp3",
        content_type="audio/mpeg",
        size_bytes=120,
        purpose="stt_audio",
        checksum="abc",
    )

    result = stt_routes.create_audio_transcribe_upload_url(
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result["asset_id"] == 10
    assert result["method"] == "PUT"
    assert manager.created_payloads[0]["filename"] == "voice.mp3"
    assert manager.created_payloads[0]["content_type"] == "audio/mpeg"
    assert manager.created_payloads[0]["size_bytes"] == 120
    assert manager.created_payloads[0]["owner"] is current_user
    assert manager.created_payloads[0]["purpose"] == "stt_audio"
    assert manager.created_payloads[0]["checksum"] == "abc"


def test_create_audio_transcribe_upload_url_rejects_bad_type():
    payload = AssetUploadUrlCreate(
        filename="voice.txt",
        content_type="text/plain",
        size_bytes=120,
        purpose="stt_audio",
    )

    with pytest.raises(HTTPException) as exc:
        stt_routes.create_audio_transcribe_upload_url(
            payload=payload,
            db=object(),
            current_user=make_user(),
        )

    assert exc.value.status_code == 415


def test_create_audio_transcribe_upload_url_rejects_bad_extension():
    payload = AssetUploadUrlCreate(
        filename="voice.exe",
        content_type="audio/mpeg",
        size_bytes=120,
        purpose="stt_audio",
    )

    with pytest.raises(HTTPException) as exc:
        stt_routes.create_audio_transcribe_upload_url(
            payload=payload,
            db=object(),
            current_user=make_user(),
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_complete_audio_transcribe_upload_downloads_asset_and_calls_stt(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)
    calls = {}

    async def fake_send_audio_to_stt(filename, content_type, content):
        calls["stt"] = (filename, content_type, content)
        return {"text": "hello"}

    monkeypatch.setattr(stt_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(stt_routes, "_send_audio_to_stt", fake_send_audio_to_stt)

    payload = AssetCompleteUploadIn(checksum="final-checksum")

    result = await stt_routes.complete_audio_transcribe_upload(
        asset_id=10,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    assert result == {"text": "hello"}
    assert manager.completed_payloads[0]["asset_id"] == 10
    assert manager.completed_payloads[0]["user"] is current_user
    assert manager.completed_payloads[0]["checksum"] == "final-checksum"
    assert manager.download_payloads[0]["asset_id"] == 10
    assert manager.download_payloads[0]["user"] is current_user
    assert calls["stt"] == ("voice.mp3", "audio/mpeg", b"audio-bytes")


@pytest.mark.asyncio
async def test_complete_audio_transcribe_upload_rejects_bad_asset_type(monkeypatch):
    db = object()
    current_user = make_user()
    manager = FakeStorageManager(db)

    def fake_complete_upload(**kwargs):
        return SimpleNamespace(
            id=10,
            original_filename="voice.txt",
            content_type="text/plain",
            size_bytes=120,
        )

    monkeypatch.setattr(manager, "complete_upload", fake_complete_upload)
    monkeypatch.setattr(stt_routes, "StorageManager", lambda db_arg: manager)

    with pytest.raises(HTTPException) as exc:
        await stt_routes.complete_audio_transcribe_upload(
            asset_id=10,
            payload=AssetCompleteUploadIn(),
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 415
