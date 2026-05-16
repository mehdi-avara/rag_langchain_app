import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from io import BytesIO

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


def test_download_comment_file_raises_404_when_disk_file_missing():
    file_rec = make_file(media_address="/tmp/definitely-missing-comment-file.txt")
    db = FakeDB(comment_result=make_comment(), file_result=file_rec)
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


def test_download_comment_file_returns_file_response(tmp_path):
    disk_file = tmp_path / "note.txt"
    disk_file.write_bytes(b"hello")

    file_rec = make_file(file_name="note.txt", media_address=str(disk_file))
    db = FakeDB(comment_result=make_comment(), file_result=file_rec)
    current_user = make_user(user_id=3)

    result = file_routes.download_comment_file(
        comment_id=10,
        file_id=20,
        db=db,
        current_user=current_user,
    )

    assert result.path == str(disk_file)
    assert result.filename == "note.txt"
    assert result.media_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_add_file_to_comment_writes_file_and_creates_record(tmp_path, monkeypatch):
    db = FakeDB(comment_result=make_comment())
    current_user = make_user(user_id=3)

    monkeypatch.setattr(file_routes.settings, "files_dir", str(tmp_path))

    upload = CommentFileUpload(
        file=UploadFile(filename="note.txt", file=BytesIO(b"hello")),
        index=False,
    )

    result = await file_routes.add_file_to_comment(
        comment_id=10,
        upload=upload,
        db=db,
        current_user=current_user,
    )

    expected_path = tmp_path / "comments" / "10" / "note.txt"

    assert expected_path.read_bytes() == b"hello"
    assert db.committed is True
    assert db.refreshed == [result]
    assert result.user_id == 3
    assert result.comment_id == 10
    assert result.file_name == "note.txt"
    assert result.media_address == str(expected_path)


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


def test_delete_comment_file_removes_disk_file_and_record(tmp_path):
    disk_file = tmp_path / "note.txt"
    disk_file.write_bytes(b"hello")

    file_rec = make_file(media_address=str(disk_file))
    db = FakeDB(comment_result=make_comment(), file_result=file_rec)
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


def test_delete_comment_file_deletes_record_when_disk_file_already_missing():
    file_rec = make_file(media_address="/tmp/definitely-missing-comment-file.txt")
    db = FakeDB(comment_result=make_comment(), file_result=file_rec)
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
