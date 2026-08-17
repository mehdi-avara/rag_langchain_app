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


def test_complete_audio_transcribe_upload_creates_task_and_dispatches_celery(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.added = []
            self.flushed = False
            self.committed = False

        def add(self, obj):
            self.added.append(obj)

        def flush(self):
            self.flushed = True

        def commit(self):
            self.committed = True

    db = FakeDB()
    current_user = make_user()
    manager = FakeStorageManager(db)
    calls = {}

    from core.celery.celery_app import celery_app

    def fake_send_task(name, args):
        calls["task"] = (name, args)
        return SimpleNamespace(id="celery-task-smoke")

    monkeypatch.setattr(stt_routes, "StorageManager", lambda db_arg: manager)
    monkeypatch.setattr(celery_app, "send_task", fake_send_task)

    result = stt_routes.complete_audio_transcribe_upload(
        asset_id=10,
        payload=AssetCompleteUploadIn(checksum="final-checksum"),
        language=None,
        db=db,
        current_user=current_user,
    )

    assert result.task_id
    assert manager.completed_payloads[0]["asset_id"] == 10
    assert manager.completed_payloads[0]["user"] is current_user
    assert manager.completed_payloads[0]["checksum"] == "final-checksum"
    assert manager.download_payloads == []
    assert calls["task"] == ("stt.transcribe_audio", [10, 3, None])
    assert db.flushed is True
    assert db.committed is True
    assert len(db.added) == 1
    assert db.added[0].task_type == "stt_transcription"
    assert db.added[0].status == "pending"
    assert db.added[0].created_by_user_id == 3
    assert db.added[0].celery_task_id == "celery-task-smoke"


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


class FakeDirectAudioUpload:
    def __init__(
        self,
        content: bytes,
        *,
        filename: str = "voice.mp3",
        content_type: str = "audio/mpeg",
    ):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._offset = 0
        self.read_sizes = []

    async def read(self, size: int = -1):
        self.read_sizes.append(size)

        if self._offset >= len(self._content):
            return b""

        if size is None or size < 0:
            end = len(self._content)
        else:
            end = min(
                len(self._content),
                self._offset + size,
            )

        chunk = self._content[
            self._offset:end
        ]
        self._offset = end
        return chunk


@pytest.mark.asyncio
async def test_direct_transcribe_uses_bounded_reads_and_forwards_audio(
    monkeypatch,
):
    monkeypatch.setattr(
        stt_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        10,
    )

    upload = FakeDirectAudioUpload(
        b"0123456789"
    )

    captured = {}

    async def fake_send_audio_to_stt(
        filename,
        content_type,
        content,
    ):
        captured["filename"] = filename
        captured["content_type"] = content_type
        captured["content"] = content.read()
        return {"text": "ok"}

    monkeypatch.setattr(
        stt_routes,
        "_send_audio_to_stt",
        fake_send_audio_to_stt,
    )

    result = await stt_routes.transcribe(
        current_user=make_user(),
        file=upload,
    )

    assert result == {"text": "ok"}
    assert captured["filename"] == "voice.mp3"
    assert captured["content_type"] == "audio/mpeg"
    assert captured["content"] == b"0123456789"

    assert upload.read_sizes
    assert -1 not in upload.read_sizes
    assert all(
        size == stt_routes._AUDIO_UPLOAD_CHUNK_SIZE
        for size in upload.read_sizes
    )


@pytest.mark.asyncio
async def test_direct_transcribe_rejects_oversize_before_downstream(
    monkeypatch,
):
    monkeypatch.setattr(
        stt_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        4,
    )

    upload = FakeDirectAudioUpload(
        b"12345"
    )

    downstream_called = False

    async def fake_send_audio_to_stt(
        filename,
        content_type,
        content,
    ):
        nonlocal downstream_called
        downstream_called = True
        return {"text": "unexpected"}

    monkeypatch.setattr(
        stt_routes,
        "_send_audio_to_stt",
        fake_send_audio_to_stt,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        await stt_routes.transcribe(
            current_user=make_user(),
            file=upload,
        )

    assert exc.value.status_code == 413
    assert downstream_called is False
    assert upload.read_sizes
    assert -1 not in upload.read_sizes
