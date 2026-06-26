"""Tests for MinerU → S3 persistence and chunk-image association.

Covers: image-ref rewriting, processed-bundle discovery, StorageManager derived
helpers (with an in-memory fake S3 client), retrieval-time content rendering,
figure extraction / chunk-image rows, and the DI S3 middle.json reader.
"""

import os
import sys
from types import SimpleNamespace

# Compatibility shim for this test sandbox only: the repo imports
# ``langchain.text_splitter`` (present in the project's pinned langchain), but a
# newer langchain in this environment exposes the class at
# ``langchain_text_splitters``. Alias it so importing core.simple_ingestion works
# here; on CI (pinned deps) the real module is used and this is a no-op.
if "langchain.text_splitter" not in sys.modules:
    try:
        import langchain.text_splitter  # noqa: F401
    except Exception:
        try:
            import langchain_text_splitters as _lts
            sys.modules["langchain.text_splitter"] = _lts
        except Exception:
            pass

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

import pytest


# ---------------------------------------------------------------------------
# P1.3 — image-reference rewriting
# ---------------------------------------------------------------------------

def _sample_pdf_info():
    return [
        {
            "page_idx": 0,
            "para_blocks": [
                {
                    "type": "image",
                    "bbox": [1, 2, 3, 4],
                    "blocks": [
                        {
                            "type": "image_body",
                            "lines": [{"spans": [{"type": "image", "image_path": "a0223b5f.jpg", "bbox": [1, 2, 3, 4]}]}],
                        },
                        {
                            "type": "image_caption",
                            "lines": [{"spans": [{"type": "text", "content": "Figure 1"}]}],
                        },
                    ],
                },
                {
                    "type": "text",
                    "lines": [{"spans": [{"type": "text", "content": "hello world body text"}]}],
                },
            ],
        }
    ]


def test_rewrite_middle_json_image_refs_rewrites_and_preserves_name():
    from core.mineru_artifacts import rewrite_middle_json_image_refs, canonical_image_ref

    pdf_info = _sample_pdf_info()
    names = rewrite_middle_json_image_refs(pdf_info, 7)

    assert names == ["a0223b5f.jpg"]
    span = pdf_info[0]["para_blocks"][0]["blocks"][0]["lines"][0]["spans"][0]
    assert span["image_path"] == canonical_image_ref(7, "a0223b5f.jpg")
    assert span["image_path"] == "/documents/7/images/a0223b5f.jpg"
    assert span["image_name"] == "a0223b5f.jpg"


def test_rewrite_is_idempotent_and_leaves_no_bare_filenames():
    from core.mineru_artifacts import rewrite_middle_json_image_refs

    pdf_info = _sample_pdf_info()
    rewrite_middle_json_image_refs(pdf_info, 7)
    names2 = rewrite_middle_json_image_refs(pdf_info, 7)

    span = pdf_info[0]["para_blocks"][0]["blocks"][0]["lines"][0]["spans"][0]
    assert names2 == ["a0223b5f.jpg"]
    assert span["image_path"] == "/documents/7/images/a0223b5f.jpg"
    assert span["image_name"] == "a0223b5f.jpg"


def test_rewrite_skips_http_and_data_urls():
    from core.mineru_artifacts import rewrite_middle_json_image_refs

    pdf_info = [{"para_blocks": [{"type": "image", "blocks": [
        {"type": "image_body", "lines": [{"spans": [{"type": "image", "image_path": "https://cdn/x.png"}]}]},
    ]}]}]
    names = rewrite_middle_json_image_refs(pdf_info, 3)
    assert names == []
    span = pdf_info[0]["para_blocks"][0]["blocks"][0]["lines"][0]["spans"][0]
    assert span["image_path"] == "https://cdn/x.png"


# ---------------------------------------------------------------------------
# Chunk builder consumes rewritten refs + emits per-chunk figure metadata
# ---------------------------------------------------------------------------

def test_chunk_builder_uses_canonical_path_and_emits_images():
    from core.mineru_artifacts import rewrite_middle_json_image_refs
    from components.stand_alone_functions.page_find_logic.mineru_main_file_creator import (
        build_dual_mode_chunks_from_pdf_info,
    )

    pdf_info = _sample_pdf_info()
    rewrite_middle_json_image_refs(pdf_info, 7)
    chunks, _ = build_dual_mode_chunks_from_pdf_info(pdf_info, doc_id=7, base_url="https://h", min_chunk_tokens=1)

    joined = "\n".join(c["chunk_text"] for c in chunks)
    assert "/documents/7/images/a0223b5f.jpg" in joined
    # No double-prefixed bucket path leaked in.
    assert "images//documents" not in joined

    all_images = [img for c in chunks for img in c.get("images", [])]
    assert any(img["filename"] == "a0223b5f.jpg" and img["caption"] == "Figure 1" for img in all_images)


def test_extract_figure_refs_skips_non_figure_block():
    from components.stand_alone_functions.page_find_logic.mineru_main_file_creator import (
        extract_figure_refs_from_block,
    )

    block = {"type": "text", "lines": [{"spans": [{"type": "text", "content": "x"}]}]}
    assert extract_figure_refs_from_block(block, 0) == []


# ---------------------------------------------------------------------------
# P1.2 — processed-bundle discovery (method-agnostic)
# ---------------------------------------------------------------------------

def test_find_processed_bundle_discovers_vlm_subfolder(tmp_path):
    from components.folders import find_processed_bundle, find_processed_images_dir

    method_dir = tmp_path / "original" / "vlm"
    images_dir = method_dir / "images"
    images_dir.mkdir(parents=True)
    (method_dir / "doc_middle.json").write_text("{}")
    (images_dir / "fig.jpg").write_bytes(b"img")

    bundle = find_processed_bundle(tmp_path)
    assert bundle.middle_json is not None and bundle.middle_json.name == "doc_middle.json"
    assert bundle.images_dir == images_dir
    assert bundle.method_dir == method_dir
    assert find_processed_images_dir(tmp_path) == images_dir


def test_find_processed_bundle_missing_dir_returns_none(tmp_path):
    from components.folders import find_processed_bundle

    bundle = find_processed_bundle(tmp_path / "nope")
    assert bundle.middle_json is None and bundle.images_dir is None


# ---------------------------------------------------------------------------
# P1.1 — StorageManager derived helpers (in-memory fake S3 client)
# ---------------------------------------------------------------------------

class _FakeS3Client:
    def __init__(self):
        self.objects = {}

    def head_bucket(self, **kwargs):
        return {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = (Body, ContentType)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        with open(filename, "rb") as fh:
            self.objects[key] = (fh.read(), (ExtraArgs or {}).get("ContentType"))

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "GetObject")
        body, ct = self.objects[Key]
        return {"Body": _FakeBody(body), "ContentType": ct}


class _FakeBody:
    """Minimal StreamingBody emulation: read([amt]) then EOF."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, amt=None):
        if self._pos >= len(self._data):
            return b""
        if amt is None:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + amt]
            self._pos += len(chunk)
        return chunk

    def close(self):
        pass


def _make_manager():
    from storage.manager import StorageManager

    mgr = StorageManager.__new__(StorageManager)
    mgr.db = None
    mgr.bucket = "test-bucket"
    fake = _FakeS3Client()
    mgr.client = fake
    mgr.presign_client = fake
    return mgr, fake


def test_derived_key_layout():
    from storage.manager import StorageManager

    asset = SimpleNamespace(id=42, company_id=9)
    assert StorageManager.derived_prefix(asset) == "companies/9/assets/42/mineru"
    assert StorageManager.derived_key(asset, "middle.json") == "companies/9/assets/42/mineru/middle.json"
    assert StorageManager.derived_key(asset, "/images/x.jpg") == "companies/9/assets/42/mineru/images/x.jpg"


def test_upload_bytes_and_get_object_roundtrip():
    mgr, _ = _make_manager()
    key = "companies/9/assets/42/mineru/middle.json"
    mgr.upload_bytes(key=key, data=b'{"k": 1}', content_type="application/json")

    assert mgr.object_exists(key) is True
    assert mgr.object_exists("missing") is False

    fetched = mgr.get_object_bytes(key)
    assert fetched is not None
    body, ct = fetched
    assert body == b'{"k": 1}'
    assert ct == "application/json"


def test_upload_path_roundtrip(tmp_path):
    mgr, _ = _make_manager()
    src = tmp_path / "fig.jpg"
    src.write_bytes(b"binarydata")
    key = "companies/9/assets/42/mineru/images/fig.jpg"
    mgr.upload_path(key=key, path=src)

    fetched = mgr.get_object_bytes(key)
    assert fetched is not None and fetched[0] == b"binarydata"


def test_stream_object_yields_bytes_or_none():
    mgr, _ = _make_manager()
    key = "k1"
    mgr.upload_bytes(key=key, data=b"abc")
    stream = mgr.stream_object(key)
    assert stream is not None and b"".join(stream) == b"abc"
    assert mgr.stream_object("absent") is None


# ---------------------------------------------------------------------------
# P2 — image_chunk row builder
# ---------------------------------------------------------------------------

def test_build_image_chunk_rows():
    from core.simple_ingestion import _build_image_chunk_rows

    images = [{"filename": "a.jpg", "page_num": 0, "bbox": [1, 2, 3, 4], "caption": "Cap"}]
    rows = _build_image_chunk_rows(99, images, "companies/9/assets/42/mineru")
    assert len(rows) == 1
    row = rows[0]
    assert row.chunk_id == 99
    assert row.storage_key == "companies/9/assets/42/mineru/images/a.jpg"
    assert row.page_num == 0
    assert row.caption == "Cap"
    assert row.position == "a.jpg"
    assert row.bbox == [1, 2, 3, 4]


def test_build_image_chunk_rows_without_prefix_has_null_key():
    from core.simple_ingestion import _build_image_chunk_rows

    rows = _build_image_chunk_rows(1, [{"filename": "a.jpg"}], None)
    assert rows[0].storage_key is None
    assert rows[0].position == "a.jpg"


# ---------------------------------------------------------------------------
# P3 — retrieval-time content rendering
# ---------------------------------------------------------------------------

def test_render_chunk_content_presigns_existing_object(monkeypatch):
    import core.chunk_render as cr

    class FakeManager:
        def __init__(self, db):
            pass

        def object_exists(self, key):
            return True

        def create_presigned_get_for_key(self, key):
            return f"https://signed/{key}?sig=1"

    monkeypatch.setattr("storage.manager.StorageManager", FakeManager)

    doc = SimpleNamespace(id=7, mineru_prefix="companies/9/assets/42/mineru")
    content = "See ![](/documents/7/images/a0223b5f.jpg) here"
    out = cr.render_chunk_content_for_client(content, doc, db=None)
    assert "https://signed/companies/9/assets/42/mineru/images/a0223b5f.jpg" in out
    assert "/documents/7/images/a0223b5f.jpg" not in out


def test_render_chunk_content_falls_back_when_no_prefix():
    import core.chunk_render as cr

    doc = SimpleNamespace(id=7, mineru_prefix=None)
    content = "![](/documents/7/images/a.jpg)"
    out = cr.render_chunk_content_for_client(content, doc, db=None)
    # Falls back to absolute app-route URL.
    assert out.endswith("/documents/7/images/a.jpg)")
    assert "http" in out


def test_build_chunk_images_from_rows(monkeypatch):
    import core.chunk_render as cr

    class FakeManager:
        def __init__(self, db):
            pass

        def object_exists(self, key):
            return True

        def create_presigned_get_for_key(self, key):
            return f"https://signed/{key}"

    monkeypatch.setattr("storage.manager.StorageManager", FakeManager)

    doc = SimpleNamespace(id=7, mineru_prefix="companies/9/assets/42/mineru")
    row = SimpleNamespace(storage_key="companies/9/assets/42/mineru/images/a.jpg", caption="Cap", page_num=2, position="a.jpg")
    chunk = SimpleNamespace(image_data=[row])
    images = cr.build_chunk_images(chunk, doc, db=None)
    assert images == [{"url": "https://signed/companies/9/assets/42/mineru/images/a.jpg", "caption": "Cap", "page_num": 2}]


def test_build_chunk_images_empty_when_no_rows():
    import core.chunk_render as cr

    doc = SimpleNamespace(id=7, mineru_prefix="p")
    chunk = SimpleNamespace(image_data=[])
    assert cr.build_chunk_images(chunk, doc, db=None) == []


# ---------------------------------------------------------------------------
# P5 — DI reads middle.json from S3
# ---------------------------------------------------------------------------

def test_page_text_from_s3(monkeypatch):
    import json
    from document_intelligence.services import mineru_source

    middle = {"pdf_info": [{"page_idx": 0, "para_blocks": [
        {"type": "text", "lines": [{"spans": [{"type": "text", "content": "Hello S3"}]}]}
    ]}]}

    class FakeManager:
        def __init__(self, db):
            pass

        def get_object_bytes(self, key):
            assert key == "companies/9/assets/42/mineru/middle.json"
            return json.dumps(middle).encode("utf-8"), "application/json"

    monkeypatch.setattr("storage.manager.StorageManager", FakeManager)

    doc = SimpleNamespace(id=5, mineru_prefix="companies/9/assets/42/mineru")
    text = mineru_source.page_text_from_s3(db=None, document=doc)
    assert text == {1: "Hello S3"}


def test_page_text_from_s3_no_prefix_returns_empty():
    from document_intelligence.services import mineru_source

    doc = SimpleNamespace(id=5, mineru_prefix=None)
    assert mineru_source.page_text_from_s3(db=None, document=doc) == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
