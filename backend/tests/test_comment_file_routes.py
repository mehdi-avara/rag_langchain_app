import os
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from io import BytesIO
from starlette.datastructures import Headers

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

from Models import Comment, CommentFile, CommentType
from routs.comments import files as file_routes
from schemas.comment import CommentFileUpload


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
        if self.target is Comment:
            return self.db.comment_result
        if self.target is CommentFile:
            return self.db.file_result
        return None

    def all(self):
        if self.target is CommentFile:
            return self.db.file_rows
        return []


class FakeDB:
    def __init__(self, comment_result=None, file_result=None, file_rows=None):
        self.comment_result = comment_result
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
        self.refreshed.append(obj)


class FakeUploadFile:
    def __init__(self, filename="note.txt", content=b"hello"):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


def make_user(user_id=3):
    return SimpleNamespace(id=user_id, company_id=1, role="user", roles=[])


def make_comment(comment_id=10, user_id=3):
    return SimpleNamespace(
        id=comment_id,
        user_id=user_id,
        title="Title",
        content="Content",
        type=CommentType.COMMENT,
        created_at=datetime(2026, 5, 16, 10, 0, 0),
        files=[],
    )


def make_file(file_id=20, user_id=3, comment_id=10, file_name="note.txt", media_address="/tmp/note.txt"):
    return SimpleNamespace(
        id=file_id,
        user_id=user_id,
        comment_id=comment_id,
        file_name=file_name,
        media_address=media_address,
    )


def test_parse_file_upload_wraps_upload_file():
    upload_file = UploadFile(filename="a.txt", file=BytesIO(b"hello"))

    result = file_routes._parse_file_upload(file=upload_file, index=True)

    assert result.file is upload_file
    assert result.index is True


def test_get_owned_comment_returns_comment():
    comment = make_comment()
    db = FakeDB(comment_result=comment)
    current_user = make_user(user_id=3)

    result = file_routes._get_owned_comment(db, comment_id=10, current_user=current_user)

    assert result is comment


def test_get_owned_comment_raises_404_when_missing_or_not_owned():
    db = FakeDB(comment_result=None)
    current_user = make_user(user_id=3)

    with pytest.raises(HTTPException) as exc:
        file_routes._get_owned_comment(db, comment_id=10, current_user=current_user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Comment not found"


def test_list_comment_files_checks_comment_ownership_and_returns_files():
    files = [
        make_file(1, file_name="a.txt"),
        make_file(2, file_name="b.txt"),
    ]
    db = FakeDB(comment_result=make_comment(), file_rows=files)
    current_user = make_user(user_id=3)

    result = file_routes.list_comment_files(comment_id=10, db=db, current_user=current_user)

    assert result == files
    assert db.queries[-1].ordered is True


def test_download_comment_file_raises_404_when_record_missing():
    db = FakeDB(comment_result=make_comment(), file_result=None)
    current_user = make_user(user_id=3)

    with pytest.raises(HTTPException) as exc:
        file_routes.download_comment_file(
            comment_id=10,
            file_id=99,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "File not found for this comment"


def test_download_comment_file_raises_404_when_disk_file_missing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )

    missing = (
        tmp_path
        / "comments"
        / "10"
        / "definitely-missing-comment-file.txt"
    )

    file_rec = make_file(
        media_address=str(missing),
    )
    db = FakeDB(
        comment_result=make_comment(),
        file_result=file_rec,
    )
    current_user = make_user(user_id=3)

    with pytest.raises(HTTPException) as exc:
        file_routes.download_comment_file(
            comment_id=10,
            file_id=20,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Stored file is missing"


def test_download_comment_file_returns_file_response(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )

    disk_file = (
        tmp_path
        / "comments"
        / "10"
        / "note.txt"
    )
    disk_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    disk_file.write_bytes(b"hello")

    file_rec = make_file(
        file_name="note.txt",
        media_address=str(disk_file),
    )
    db = FakeDB(
        comment_result=make_comment(),
        file_result=file_rec,
    )
    current_user = make_user(user_id=3)

    result = file_routes.download_comment_file(
        comment_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert Path(result.path).resolve() == disk_file.resolve()
    assert result.filename == "note.txt"
    assert result.media_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_add_file_to_comment_writes_file_and_creates_record(tmp_path, monkeypatch):
    db = FakeDB(comment_result=make_comment())
    current_user = make_user(user_id=3)

    monkeypatch.setattr(file_routes.settings, "files_dir", str(tmp_path))
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        1024,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    upload = CommentFileUpload(
        file=UploadFile(
            filename="note.txt",
            file=BytesIO(b"hello"),
            headers=Headers(
                {"content-type": "text/plain"}
            ),
        ),
        index=False,
    )

    result = await file_routes.add_file_to_comment(
        comment_id=10,
        upload=upload,
        db=db,
        current_user=current_user,
    )

    stored_path = Path(result.media_address)
    allowed_base = (
        tmp_path
        / "comments"
        / "10"
    ).resolve()

    assert stored_path.is_file()
    assert stored_path.read_bytes() == b"hello"
    assert stored_path.resolve().is_relative_to(allowed_base)
    assert stored_path.name != "note.txt"
    assert stored_path.suffix == ".upload"

    assert db.committed is True
    assert db.refreshed == [result]
    assert result.user_id == 3
    assert result.comment_id == 10
    assert result.file_name == "note.txt"


def test_delete_comment_file_raises_404_when_record_missing():
    db = FakeDB(comment_result=make_comment(), file_result=None)
    current_user = make_user(user_id=3)

    with pytest.raises(HTTPException) as exc:
        file_routes.delete_comment_file(
            comment_id=10,
            file_id=20,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "File not found for this comment"


def test_delete_comment_file_removes_disk_file_and_record(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )

    disk_file = (
        tmp_path
        / "comments"
        / "10"
        / "note.txt"
    )
    disk_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    disk_file.write_bytes(b"hello")

    file_rec = make_file(
        media_address=str(disk_file),
    )
    db = FakeDB(
        comment_result=make_comment(),
        file_result=file_rec,
    )
    current_user = make_user(user_id=3)

    result = file_routes.delete_comment_file(
        comment_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert not disk_file.exists()
    assert db.deleted == [file_rec]
    assert db.committed is True


def test_delete_comment_file_deletes_record_when_disk_file_already_missing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )

    missing = (
        tmp_path
        / "comments"
        / "10"
        / "definitely-missing-comment-file.txt"
    )

    file_rec = make_file(
        media_address=str(missing),
    )
    db = FakeDB(
        comment_result=make_comment(),
        file_result=file_rec,
    )
    current_user = make_user(user_id=3)

    result = file_routes.delete_comment_file(
        comment_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result is None
    assert db.deleted == [file_rec]
    assert db.committed is True

def _make_upload_file(
    filename: str,
    data: bytes,
    content_type: str,
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(data),
        headers=Headers(
            {"content-type": content_type}
        ),
    )


@pytest.mark.asyncio
async def test_legacy_comment_upload_does_not_use_user_path(
    tmp_path,
    monkeypatch,
):
    db = FakeDB(
        comment_result=make_comment(),
    )
    current_user = make_user(user_id=3)

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        1024,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")

    upload = CommentFileUpload(
        file=_make_upload_file(
            filename="../../outside.txt",
            data=b"new",
            content_type="text/plain",
        ),
        index=False,
    )

    result = await file_routes.add_file_to_comment(
        comment_id=10,
        upload=upload,
        db=db,
        current_user=current_user,
    )

    stored = Path(result.media_address)
    allowed = (
        tmp_path
        / "comments"
        / "10"
    ).resolve()

    assert outside.read_bytes() == b"keep"
    assert stored.is_file()
    assert stored.read_bytes() == b"new"
    assert stored.resolve().is_relative_to(allowed)
    assert result.file_name == "outside.txt"


@pytest.mark.asyncio
async def test_legacy_comment_upload_does_not_overwrite_absolute_path(
    tmp_path,
    monkeypatch,
):
    db = FakeDB(
        comment_result=make_comment(),
    )
    current_user = make_user(user_id=3)

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        1024,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    outside = tmp_path / "absolute-target.txt"
    outside.write_bytes(b"keep")

    upload = CommentFileUpload(
        file=_make_upload_file(
            filename=str(outside),
            data=b"overwrite-attempt",
            content_type="text/plain",
        ),
        index=False,
    )

    result = await file_routes.add_file_to_comment(
        comment_id=10,
        upload=upload,
        db=db,
        current_user=current_user,
    )

    assert outside.read_bytes() == b"keep"
    assert Path(result.media_address).read_bytes() == b"overwrite-attempt"
    assert result.file_name == "absolute-target.txt"


@pytest.mark.asyncio
async def test_legacy_comment_upload_rejects_disallowed_content_type(
    tmp_path,
    monkeypatch,
):
    db = FakeDB(
        comment_result=make_comment(),
    )
    current_user = make_user(user_id=3)

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        1024,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    upload = CommentFileUpload(
        file=_make_upload_file(
            filename="payload.bin",
            data=b"payload",
            content_type="application/octet-stream",
        ),
        index=False,
    )

    with pytest.raises(HTTPException) as exc:
        await file_routes.add_file_to_comment(
            comment_id=10,
            upload=upload,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 415

    assert [
        item
        for item in tmp_path.rglob("*")
        if item.is_file()
    ] == []


@pytest.mark.asyncio
async def test_legacy_comment_upload_rejects_oversize_and_cleans_partial(
    tmp_path,
    monkeypatch,
):
    db = FakeDB(
        comment_result=make_comment(),
    )
    current_user = make_user(user_id=3)

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        5,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    upload = CommentFileUpload(
        file=_make_upload_file(
            filename="large.txt",
            data=b"123456",
            content_type="text/plain",
        ),
        index=False,
    )

    with pytest.raises(HTTPException) as exc:
        await file_routes.add_file_to_comment(
            comment_id=10,
            upload=upload,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 413
    assert exc.value.detail == "Comment file is too large"

    assert [
        item
        for item in tmp_path.rglob("*")
        if item.is_file()
    ] == []


@pytest.mark.asyncio
async def test_legacy_comment_upload_rejects_empty_file(
    tmp_path,
    monkeypatch,
):
    db = FakeDB(
        comment_result=make_comment(),
    )
    current_user = make_user(user_id=3)

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path),
    )
    monkeypatch.setattr(
        file_routes.settings,
        "MAX_UPLOAD_SIZE_BYTES",
        1024,
    )
    monkeypatch.setattr(
        file_routes.settings,
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "text/plain",
    )

    upload = CommentFileUpload(
        file=_make_upload_file(
            filename="empty.txt",
            data=b"",
            content_type="text/plain",
        ),
        index=False,
    )

    with pytest.raises(HTTPException) as exc:
        await file_routes.add_file_to_comment(
            comment_id=10,
            upload=upload,
            db=db,
            current_user=current_user,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Invalid file size"


def test_legacy_comment_download_rejects_outside_path(
    tmp_path,
    monkeypatch,
):
    foreign = tmp_path / "foreign.txt"
    foreign.write_bytes(b"secret")

    user = make_user(user_id=3)
    comment = make_comment()
    file_rec = make_file(
        media_address=str(foreign),
    )

    db = FakeDB(
        comment_result=comment,
        file_result=file_rec,
    )

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path / "storage"),
    )

    with pytest.raises(HTTPException) as exc:
        file_routes.download_comment_file(
            comment_id=10,
            file_id=20,
            db=db,
            current_user=user,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid comment file path"
    assert foreign.read_bytes() == b"secret"


def test_legacy_comment_delete_rejects_outside_path(
    tmp_path,
    monkeypatch,
):
    foreign = tmp_path / "foreign.txt"
    foreign.write_bytes(b"keep")

    user = make_user(user_id=3)
    comment = make_comment()
    file_rec = make_file(
        media_address=str(foreign),
    )

    db = FakeDB(
        comment_result=comment,
        file_result=file_rec,
    )

    monkeypatch.setattr(
        file_routes.settings,
        "files_dir",
        str(tmp_path / "storage"),
    )

    with pytest.raises(HTTPException) as exc:
        file_routes.delete_comment_file(
            comment_id=10,
            file_id=20,
            db=db,
            current_user=user,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid comment file path"
    assert foreign.read_bytes() == b"keep"
    assert db.deleted == []
    assert db.committed is False
