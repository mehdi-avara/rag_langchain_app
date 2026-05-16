import io
import json
import os
import sys
import types
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

mineru_mod = types.ModuleType("mineru")
mineru_backend = types.ModuleType("mineru.backend")
mineru_pipeline = types.ModuleType("mineru.backend.pipeline")
mineru_para_split = types.ModuleType("mineru.backend.pipeline.para_split")
mineru_para_split.ListLineTag = type("ListLineTag", (), {"IS_LIST_START_LINE": "is_list_start_line"})
mineru_utils = types.ModuleType("mineru.utils")
mineru_cfg = types.ModuleType("mineru.utils.config_reader")
mineru_cfg.get_latex_delimiter_config = lambda: {}
mineru_enum = types.ModuleType("mineru.utils.enum_class")
mineru_enum.BlockType = type(
    "BlockType",
    (),
    {
        "TEXT": "text",
        "LIST": "list",
        "INDEX": "index",
        "TITLE": "title",
        "INTERLINE_EQUATION": "interline_equation",
        "IMAGE": "image",
        "TABLE": "table",
        "IMAGE_FOOTNOTE": "image_footnote",
        "IMAGE_CAPTION": "image_caption",
        "IMAGE_BODY": "image_body",
        "TABLE_CAPTION": "table_caption",
        "TABLE_BODY": "table_body",
        "TABLE_FOOTNOTE": "table_footnote",
    },
)
mineru_enum.ContentType = type("ContentType", (), {"IMAGE": "image", "TABLE": "table", "TEXT": "text"})
mineru_enum.MakeMode = type("MakeMode", (), {"NLP_MD": "nlp_md", "MM_MD": "mm_md"})
mineru_language = types.ModuleType("mineru.utils.language")
mineru_language.detect_lang = lambda _text: "en"
sys.modules.setdefault("mineru", mineru_mod)
sys.modules.setdefault("mineru.backend", mineru_backend)
sys.modules.setdefault("mineru.backend.pipeline", mineru_pipeline)
sys.modules.setdefault("mineru.backend.pipeline.para_split", mineru_para_split)
sys.modules.setdefault("mineru.utils", mineru_utils)
sys.modules.setdefault("mineru.utils.config_reader", mineru_cfg)
sys.modules.setdefault("mineru.utils.enum_class", mineru_enum)
sys.modules.setdefault("mineru.utils.language", mineru_language)

import deps
from Models import Chunk, Document, DocumentStatusType, User
from db.base import Base
from db.init_db import get_db
from routs.documents import router as document_router


def _build_zip(
    *,
    include_pdf: bool = True,
    include_middle: bool = True,
    include_images: bool = False,
    include_zip_slip: bool = False,
) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if include_pdf:
            zf.writestr("input/my_file.pdf", b"%PDF-1.4\n%minimal test pdf\n")
        if include_middle:
            zf.writestr(
                "mineru/result_middle.json",
                json.dumps({"pdf_info": [{"page_idx": 0}, {"page_idx": 1}]}),
            )
        if include_images:
            zf.writestr("images/page_1.png", b"fake-image")
        if include_zip_slip:
            zf.writestr("../escape.txt", b"blocked")
    return payload.getvalue()


@pytest.fixture
def import_zip_context(tmp_path, monkeypatch):
    files_root = tmp_path / "uploaded_files"
    files_root.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        db.add(User(username="tester", First_name="Tester", pw_hash="x", role="user"))
        db.commit()

    app = FastAPI()
    app.include_router(document_router, prefix="/documents")
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id=1, role="user", company_id=1)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("routs.documents.settings.files_dir", str(files_root))

    client = TestClient(app)
    try:
        yield client, SessionLocal, files_root
    finally:
        client.close()
        engine.dispose()


def test_import_processed_zip_success(import_zip_context, monkeypatch):
    client, SessionLocal, files_root = import_zip_context

    class _DummyEncoder:
        def encode(self, _text):
            return [1]

    monkeypatch.setattr("tiktoken.encoding_for_model", lambda _model: _DummyEncoder())

    def fake_chunk_text(**kwargs):
        assert kwargs["max_tokens"] == 800
        assert kwargs["overlap_tokens"] == 150
        assert kwargs["min_chunk_tokens"] == 20
        return [
            {"chunk_text": "alpha chunk", "chunk_embedding_text": "alpha emb", "start_page": 0, "token_count": 11},
            {"chunk_text": "beta chunk", "chunk_embedding_text": "beta emb", "start_page": 1, "token_count": 13},
        ]

    def fake_embeddings(chunks):
        assert chunks == ["search_document: alpha emb", "search_document: beta emb"]
        return [[0.1] * 1024, [0.2] * 1024]

    monkeypatch.setattr("core.simple_ingestion.chunk_text", fake_chunk_text)
    monkeypatch.setattr("core.simple_ingestion.generate_embeddings_for_chunks", fake_embeddings)

    package = _build_zip(include_pdf=True, include_middle=True, include_images=True)
    response = client.post(
        "/documents/import-processed-zip",
        files={"package": ("processed.zip", package, "application/zip")},
        data={"display_filename": "Imported Package.pdf"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == DocumentStatusType.DONE.value
    assert payload["n_pages"] == 2
    assert payload["n_chunks"] == 2

    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.id == payload["doc_id"]).first()
        assert doc is not None
        assert doc.filename == "Imported Package.pdf"
        assert doc.status == DocumentStatusType.DONE.value
        assert doc.n_pages == 2
        assert doc.n_chunks == 2
        assert doc.file_path == str(doc.id)

        chunks = db.query(Chunk).filter(Chunk.doc_id == doc.id).order_by(Chunk.id.asc()).all()
        assert len(chunks) == 2
        assert chunks[0].chunk_type == "text"
        assert chunks[0].vdb_id == f"{doc.id}_0"
        assert chunks[0].es_id == f"{doc.id}_0"
        assert chunks[1].vdb_id == f"{doc.id}_1"

        doc_dir = files_root / str(doc.id)
        assert (doc_dir / "original.pdf").exists()
        assert (doc_dir / "input" / "my_file.pdf").exists()
        assert (doc_dir / "mineru" / "result_middle.json").exists()
        assert (doc_dir / "images" / "page_1.png").exists()


def test_import_processed_zip_rejects_missing_pdf(import_zip_context):
    client, SessionLocal, _ = import_zip_context
    package = _build_zip(include_pdf=False, include_middle=True)
    response = client.post(
        "/documents/import-processed-zip",
        files={"package": ("processed.zip", package, "application/zip")},
    )

    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.query(Document).count() == 0


def test_import_processed_zip_rejects_missing_middle_json(import_zip_context):
    client, SessionLocal, _ = import_zip_context
    package = _build_zip(include_pdf=True, include_middle=False)
    response = client.post(
        "/documents/import-processed-zip",
        files={"package": ("processed.zip", package, "application/zip")},
    )

    assert response.status_code == 400
    assert "middle" in response.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.query(Document).count() == 0


def test_import_processed_zip_blocks_zip_slip(import_zip_context):
    client, SessionLocal, files_root = import_zip_context
    package = _build_zip(include_pdf=True, include_middle=True, include_zip_slip=True)
    response = client.post(
        "/documents/import-processed-zip",
        files={"package": ("processed.zip", package, "application/zip")},
    )

    assert response.status_code == 400
    assert "invalid zip entry path" in response.json()["detail"].lower()
    assert not (files_root / "escape.txt").exists()
    with SessionLocal() as db:
        assert db.query(Document).count() == 0
