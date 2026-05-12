from typing import List, Optional
from fastapi import Depends, APIRouter, UploadFile, status, Response, HTTPException, Query, Request, Header, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
import os
import io
import json
import shutil
import zipfile
import posixpath

from core.semantic_ask import generate_answer_from_references, parse_semantic_citations
from deps import require_permission
from Models import User, Document, Chunk, DocumentStatusType
from db.init_db import get_db
from db.search_connector import search_documents_text, search_document_part_hits_semantic
from schemas.document import DocumentOut, ChunkOut
from schemas.search import (
    TextSearchRequest,
    SemanticSearchRequest,
    DocumentSemanticHit,
    DocumentAskRequest,
    DocumentAskResponse,
)
from settings import get_settings


settings = get_settings()
router = APIRouter()


def _normalize_zip_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Invalid zip entry path: {name}")
    normalized = posixpath.normpath(normalized)
    if normalized in {"", "."}:
        return ""
    if normalized == ".." or normalized.startswith("../"):
        raise HTTPException(status_code=400, detail=f"Invalid zip entry path: {name}")
    if ":" in normalized.split("/", 1)[0]:
        raise HTTPException(status_code=400, detail=f"Invalid zip entry path: {name}")
    return normalized


def _validate_member_target(base_dir: Path, relative_name: str) -> Path:
    target = (base_dir / relative_name).resolve()
    base = base_dir.resolve()
    if os.path.commonpath([str(base), str(target)]) != str(base):
        raise HTTPException(status_code=400, detail=f"Invalid zip entry path: {relative_name}")
    return target


def _find_middle_json_candidate(zip_file: zipfile.ZipFile, file_entries: dict[str, zipfile.ZipInfo]) -> str:
    middle_by_name = [name for name in file_entries if name.lower().endswith("_middle.json")]
    if len(middle_by_name) == 1:
        return middle_by_name[0]
    if len(middle_by_name) > 1:
        raise HTTPException(status_code=400, detail="Zip package must contain exactly one MinerU _middle.json file")

    middle_by_content = []
    for name, info in file_entries.items():
        if not name.lower().endswith(".json"):
            continue
        try:
            with zip_file.open(info) as f:
                data = json.load(f)
        except Exception:
            continue
        pdf_info = data.get("pdf_info", data) if isinstance(data, dict) else data
        if isinstance(pdf_info, list):
            middle_by_content.append(name)

    if len(middle_by_content) == 1:
        return middle_by_content[0]
    if len(middle_by_content) > 1:
        raise HTTPException(status_code=400, detail="Zip package contains multiple middle-json candidates")
    raise HTTPException(status_code=400, detail="Zip package must contain one MinerU middle JSON file")


def _extract_zip_safely(zip_file: zipfile.ZipFile, file_entries: dict[str, zipfile.ZipInfo], dest_dir: Path) -> None:
    for relative_name, info in file_entries.items():
        target_path = _validate_member_target(dest_dir, relative_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zip_file.open(info) as src, open(target_path, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _get_company_document(db: Session, doc_id: int, current_user: User) -> Document:
    if current_user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")

    doc = (
        db.query(Document)
        .join(User, User.id == Document.owner_id)
        .filter(
            Document.id == doc_id,
            User.company_id == current_user.company_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/upload")
def upload_pdf_mineru(
    file: UploadFile,
    current_user: User = Depends(require_permission("documents:create")),
    db: Session = Depends(get_db),
):
    file_bytes = file.file.read()

    if not file_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    doc = Document(
        owner_id=current_user.id,
        filename=file.filename,
        n_pages=0,
        n_chunks=0,
        file_path=None,
        status=DocumentStatusType.QUEUED,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    temp_path = os.path.join(settings.files_dir, f"{doc.id}")
    os.makedirs(temp_path, exist_ok=True)
    original_pdf = os.path.join(temp_path, "original.pdf")

    with open(original_pdf, "wb") as f:
        f.write(file_bytes)

    from core.celery.tasks import mineru_process_pdf

    mineru_process_pdf.delay(
        pdf_path=os.path.join(f"{doc.id}", "original.pdf"),
        doc_id=doc.id,
    )

    return {"doc_id": doc.id, "status": DocumentStatusType.QUEUED.value}


@router.post("/import-processed-zip", status_code=status.HTTP_200_OK)
async def import_processed_zip(
    package: UploadFile = File(...),
    display_filename: Optional[str] = Form(None),
    current_user: User = Depends(require_permission("documents:create")),
    db: Session = Depends(get_db),
):
    package_bytes = await package.read()
    package_stream = io.BytesIO(package_bytes)

    if not zipfile.is_zipfile(package_stream):
        raise HTTPException(status_code=400, detail="Uploaded package must be a valid .zip file")
    package_stream.seek(0)

    with zipfile.ZipFile(package_stream) as zip_file:
        file_entries: dict[str, zipfile.ZipInfo] = {}

        for info in zip_file.infolist():
            if info.is_dir():
                continue
            relative_name = _normalize_zip_member_name(info.filename)
            if not relative_name:
                continue
            if relative_name in file_entries:
                raise HTTPException(status_code=400, detail=f"Duplicate zip entry: {relative_name}")
            file_entries[relative_name] = info

        pdf_candidates = [name for name in file_entries if name.lower().endswith(".pdf")]

        if len(pdf_candidates) != 1:
            raise HTTPException(status_code=400, detail="Zip package must contain exactly one PDF file")

        pdf_relative_name = pdf_candidates[0]
        middle_relative_name = _find_middle_json_candidate(zip_file, file_entries)
        doc_filename = (display_filename.strip() if display_filename else "") or Path(pdf_relative_name).name

        doc = Document(
            owner_id=current_user.id,
            filename=doc_filename,
            n_pages=0,
            n_chunks=0,
            file_path=None,
            status=DocumentStatusType.INPROGGRESS.value,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        try:
            doc_dir = Path(settings.files_dir) / str(doc.id)
            doc_dir.mkdir(parents=True, exist_ok=True)
            _extract_zip_safely(zip_file, file_entries, doc_dir)

            extracted_pdf_path = _validate_member_target(doc_dir, pdf_relative_name)
            middle_json_path = _validate_member_target(doc_dir, middle_relative_name)
            original_pdf_path = doc_dir / "original.pdf"

            if extracted_pdf_path.resolve() != original_pdf_path.resolve():
                shutil.copyfile(extracted_pdf_path, original_pdf_path)

            from core.simple_ingestion import ingest_processed_middle_json

            n_pages, n_chunks = ingest_processed_middle_json(
                middle_json_path=str(middle_json_path),
                doc_id=doc.id,
                db=db,
            )

            db.query(Document).filter(Document.id == doc.id).update({
                Document.status: DocumentStatusType.DONE.value,
            })
            db.commit()

            return {
                "doc_id": doc.id,
                "status": DocumentStatusType.DONE.value,
                "n_pages": n_pages,
                "n_chunks": n_chunks,
            }

        except HTTPException:
            db.query(Document).filter(Document.id == doc.id).update({
                Document.status: DocumentStatusType.FAIELED.value,
            })
            db.commit()
            raise

        except Exception as exc:
            db.query(Document).filter(Document.id == doc.id).update({
                Document.status: DocumentStatusType.FAIELED.value,
            })
            db.commit()
            raise HTTPException(status_code=500, detail=f"Failed to import processed package: {exc}")


@router.get("", response_model=List[DocumentOut])
async def list_documents(
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    return (
        db.query(Document)
        .join(User, User.id == Document.owner_id)
        .filter(User.company_id == current_user.company_id)
        .order_by(Document.created_at.desc())
        .all()
    )


@router.post("/filter", response_model=List[DocumentOut], status_code=status.HTTP_200_OK)
async def filter_documents(
    payload: TextSearchRequest,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    return search_documents_text(
        db=db,
        query_text=payload.query,
        company_id=current_user.company_id,
        doc_ids=payload.ids or None,
        limit=payload.limit,
    )


@router.post("/semantic-search", response_model=List[DocumentSemanticHit], status_code=status.HTTP_200_OK)
async def semantic_search_documents(
    payload: SemanticSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    return search_document_part_hits_semantic(
        db=db,
        query_text=payload.query,
        company_id=current_user.company_id,
        doc_ids=payload.ids or None,
        limit=top_k,
    )


@router.post("/ask", response_model=DocumentAskResponse, status_code=status.HTTP_200_OK)
async def ask_documents(
    payload: DocumentAskRequest,
    current_user: User = Depends(require_permission("documents:ask")),
    db: Session = Depends(get_db),
):
    doc_top_k = 6 if payload.scope in {"docs", "both"} else 0
    references = (
        search_document_part_hits_semantic(
            db=db,
            query_text=payload.question,
            company_id=current_user.company_id,
            doc_ids=None,
            limit=doc_top_k,
        )
        if doc_top_k > 0
        else []
    )

    answer = await generate_answer_from_references(payload.question, references)
    used_chunk_ids, used_comment_ids, citations = parse_semantic_citations(answer)

    return {
        "answer": answer,
        "citations": citations,
        "used_chunk_ids": used_chunk_ids,
        "used_comment_ids": used_comment_ids,
        "references": references,
    }


@router.get("/download/{doc_id}")
async def download_pdf(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:download")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file path found for this document")

    file_path = Path(settings.files_dir) / doc.file_path / "original.pdf"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        filename=doc.filename,
        media_type="application/pdf",
    )


@router.get("/chunks/{chunk_id}")
async def get_chunk(
    chunk_id: int,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()

    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")

    doc = _get_company_document(db, chunk.doc_id, current_user)

    return {
        "id": chunk.id,
        "doc_id": doc.id,
        "page_num": chunk.page_num,
        "start_pos": chunk.start_pos,
        "end_pos": chunk.end_pos,
        "chunk_type": chunk.chunk_type,
        "content": chunk.content,
    }


@router.get("/stream/{doc_id}")
async def stream_pdf(
    request: Request,
    doc_id: int,
    Range: Optional[str] = Header(None, description="Byte range, e.g. 'bytes=0-65535'"),
    current_user: User = Depends(require_permission("documents:download")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file path found for this document")

    file_path = Path(settings.files_dir) / doc.file_path / "original.pdf"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    def iter_file(start: int, end: int):
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            chunk_size = 1024 * 1024

            while remaining > 0:
                data = f.read(min(chunk_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    if range_header:
        _, range_val = range_header.split("=")
        start_str, end_str = range_val.split("-")

        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1

        return StreamingResponse(
            iter_file(start, end),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "Content-Type": "application/pdf",
            },
        )

    return StreamingResponse(
        iter_file(0, file_size - 1),
        media_type="application/pdf",
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/{doc_id}", status_code=status.HTTP_200_OK, response_model=DocumentOut)
async def get_document(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    return _get_company_document(db, doc_id, current_user)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:delete")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    db.delete(doc)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{doc_id}/chunks", response_model=List[ChunkOut])
async def browse_chunks(
    doc_id: int,
    start_page: int = Query(1, ge=1),
    end_page: Optional[int] = Query(None, ge=1),
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    _get_company_document(db, doc_id, current_user)

    if end_page is None:
        end_page = start_page

    if end_page < start_page:
        raise HTTPException(status_code=400, detail="end_page must be greater than or equal to start_page")

    db_start_page = start_page - 1
    db_end_page = end_page - 1

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.doc_id == doc_id,
            Chunk.page_num >= db_start_page,
            Chunk.page_num <= db_end_page,
        )
        .order_by(Chunk.page_num.asc(), Chunk.id.asc())
        .all()
    )

    return chunks


@router.get("/{doc_id}/images/{image_path:path}")
async def get_document_image(
    doc_id: int,
    image_path: str,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file path found for this document")

    full_image_path = Path(settings.files_dir) / doc.file_path / "original" / "auto" / "images" / image_path

    try:
        full_image_path = full_image_path.resolve()
        expected_base = (Path(settings.files_dir) / doc.file_path / "original" / "auto").resolve()

        if not str(full_image_path).startswith(str(expected_base)):
            raise HTTPException(status_code=403, detail="Invalid image path")

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image path")

    if not full_image_path.exists() or not full_image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
    }

    media_type = media_types.get(full_image_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=full_image_path,
        media_type=media_type,
    )