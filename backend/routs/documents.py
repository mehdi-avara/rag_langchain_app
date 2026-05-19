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
from Models import User, Document, Chunk, DocumentStatusType, UserDocumentAccess
from db.init_db import get_db
from db.search_connector import search_documents_text, search_document_part_hits_semantic
from schemas.document import DocumentOut, ChunkOut, DocumentAccessGrantIn, DocumentAccessOut
from schemas.asset import AssetUploadUrlCreate, AssetUploadUrlOut, AssetCompleteUploadIn, AssetDownloadUrlOut
from schemas.search import (
    TextSearchRequest,
    SemanticSearchRequest,
    DocumentSemanticHit,
    DocumentAskRequest,
    DocumentAskResponse,
)
from settings import get_settings
from storage.manager import StorageManager


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


def _is_company_admin(user: User) -> bool:
    return user.role == "admin" or any(role.name == "admin" and role.is_active for role in user.roles)


def _has_document_access(db: Session, doc: Document, current_user: User, action: str) -> bool:
    if doc.owner_id == current_user.id:
        return True

    if _is_company_admin(current_user):
        return True

    access = (
        db.query(UserDocumentAccess)
        .filter(
            UserDocumentAccess.document_id == doc.id,
            UserDocumentAccess.user_id == current_user.id,
        )
        .first()
    )

    if not access:
        return False

    if action == "read":
        return access.can_read
    if action == "download":
        return access.can_download
    if action == "ask":
        return access.can_ask
    if action == "update":
        return access.can_update
    if action == "delete":
        return access.can_delete

    return False


def _get_accessible_document(db: Session, doc_id: int, current_user: User, action: str = "read") -> Document:
    doc = _get_company_document(db, doc_id, current_user)

    if not _has_document_access(db, doc, current_user, action):
        raise HTTPException(status_code=404, detail="Document not found")

    return doc

def _get_accessible_document_ids(db: Session, current_user: User, action: str = "read") -> list[int] | None:
    if current_user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")

    if _is_company_admin(current_user):
        return None

    access_column = {
        "read": UserDocumentAccess.can_read,
        "download": UserDocumentAccess.can_download,
        "ask": UserDocumentAccess.can_ask,
        "update": UserDocumentAccess.can_update,
        "delete": UserDocumentAccess.can_delete,
    }.get(action)

    if access_column is None:
        return []

    owned_ids = [
        row[0]
        for row in db.query(Document.id)
        .join(User, User.id == Document.owner_id)
        .filter(
            User.company_id == current_user.company_id,
            Document.owner_id == current_user.id,
        )
        .all()
    ]

    granted_ids = [
        row[0]
        for row in db.query(UserDocumentAccess.document_id)
        .join(Document, Document.id == UserDocumentAccess.document_id)
        .join(User, User.id == Document.owner_id)
        .filter(
            User.company_id == current_user.company_id,
            UserDocumentAccess.user_id == current_user.id,
            access_column.is_(True),
        )
        .all()
    ]

    return list(dict.fromkeys(owned_ids + granted_ids))


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


@router.post("/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_document_upload_url(
    payload: AssetUploadUrlCreate,
    current_user: User = Depends(require_permission("documents:create")),
    db: Session = Depends(get_db),
):
    if payload.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF documents are supported")

    manager = StorageManager(db)
    return manager.create_upload_url(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        owner=current_user,
        purpose="document_original_pdf",
        checksum=payload.checksum,
    )


@router.post("/complete-upload/{asset_id}", status_code=status.HTTP_201_CREATED)
def complete_document_upload(
    asset_id: int,
    payload: AssetCompleteUploadIn,
    current_user: User = Depends(require_permission("documents:create")),
    db: Session = Depends(get_db),
):
    manager = StorageManager(db)
    asset = manager.complete_upload(
        asset_id=asset_id,
        user=current_user,
        checksum=payload.checksum,
    )

    if asset.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF documents are supported")

    doc = Document(
        owner_id=current_user.id,
        original_asset_id=asset.id,
        filename=asset.original_filename,
        n_pages=0,
        n_chunks=0,
        file_path=None,
        status=DocumentStatusType.QUEUED.value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    doc_dir = Path(settings.files_dir) / str(doc.id)
    original_pdf = doc_dir / "original.pdf"

    manager.download_asset_to_path(
        asset_id=asset.id,
        user=current_user,
        target_path=original_pdf,
    )

    with original_pdf.open("rb") as f:
        header = f.read(4)

    if header != b"%PDF":
        doc.status = DocumentStatusType.FAIELED.value
        db.commit()
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF")

    from core.celery.tasks import mineru_process_pdf

    mineru_process_pdf.delay(
        pdf_path=os.path.join(f"{doc.id}", "original.pdf"),
        doc_id=doc.id,
    )

    return {
        "doc_id": doc.id,
        "asset_id": asset.id,
        "status": DocumentStatusType.QUEUED.value,
    }


@router.get("/download-url/{doc_id}", response_model=AssetDownloadUrlOut)
async def create_document_download_url(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:download")),
    db: Session = Depends(get_db),
):
    doc = _get_accessible_document(db, doc_id, current_user, "download")

    if not doc.original_asset_id:
        raise HTTPException(status_code=409, detail="This document has no asset download URL")

    manager = StorageManager(db)
    download_url = manager.create_download_url(
        asset_id=doc.original_asset_id,
        user=current_user,
        disposition="attachment",
    )

    return {
        "asset_id": doc.original_asset_id,
        "download_url": download_url,
        "expires_seconds": settings.S3_DOWNLOAD_EXPIRES_SECONDS,
    }


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
    query = (
        db.query(Document)
        .join(User, User.id == Document.owner_id)
        .filter(User.company_id == current_user.company_id)
    )

    if not _is_company_admin(current_user):
        query = (
            query
            .outerjoin(
                UserDocumentAccess,
                (UserDocumentAccess.document_id == Document.id)
                & (UserDocumentAccess.user_id == current_user.id)
            )
            .filter(
                (Document.owner_id == current_user.id)
                | (UserDocumentAccess.can_read.is_(True))
            )
        )

    return query.order_by(Document.created_at.desc()).all()


@router.post("/filter", response_model=List[DocumentOut], status_code=status.HTTP_200_OK)
async def filter_documents(
    payload: TextSearchRequest,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    allowed_doc_ids = _get_accessible_document_ids(db, current_user, "read")
    requested_ids = payload.ids or None

    if allowed_doc_ids is not None:
        if requested_ids is not None:
            doc_ids = [doc_id for doc_id in requested_ids if doc_id in set(allowed_doc_ids)]
        else:
            doc_ids = allowed_doc_ids
    else:
        doc_ids = requested_ids

    return search_documents_text(
        db=db,
        query_text=payload.query,
        company_id=current_user.company_id,
        doc_ids=doc_ids,
        limit=payload.limit,
    )


@router.post("/semantic-search", response_model=List[DocumentSemanticHit], status_code=status.HTTP_200_OK)
async def semantic_search_documents(
    payload: SemanticSearchRequest,
    top_k: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    allowed_doc_ids = _get_accessible_document_ids(db, current_user, "read")
    requested_ids = payload.ids or None

    if allowed_doc_ids is not None:
        if requested_ids is not None:
            doc_ids = [doc_id for doc_id in requested_ids if doc_id in set(allowed_doc_ids)]
        else:
            doc_ids = allowed_doc_ids
    else:
        doc_ids = requested_ids

    return search_document_part_hits_semantic(
        db=db,
        query_text=payload.query,
        company_id=current_user.company_id,
        doc_ids=doc_ids,
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
            doc_ids=_get_accessible_document_ids(db, current_user, "ask"),
            limit=doc_top_k,
        )
        if doc_top_k > 0
        else []
    )

    try:
        answer = await generate_answer_from_references(payload.question, references)
    except Exception as exc:
        raise HTTPException(status_code=504, detail=f"LLM request failed: {exc}") from exc

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
    doc = _get_accessible_document(db, doc_id, current_user, "download")

    if doc.file_path:
        file_path = Path(settings.files_dir) / doc.file_path / "original.pdf"
    else:
        file_path = Path(settings.files_dir) / str(doc.id) / "original.pdf"

    if not file_path.exists() and doc.original_asset_id:
        manager = StorageManager(db)
        manager.download_asset_to_path(
            asset_id=doc.original_asset_id,
            user=current_user,
            target_path=file_path,
        )

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

    doc = _get_accessible_document(db, chunk.doc_id, current_user, "read")

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
    doc = _get_accessible_document(db, doc_id, current_user, "download")

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



@router.get("/{doc_id}/access", response_model=List[DocumentAccessOut], status_code=status.HTTP_200_OK)
async def list_document_access(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not _is_company_admin(current_user) and doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    return (
        db.query(UserDocumentAccess)
        .filter(UserDocumentAccess.document_id == doc.id)
        .order_by(UserDocumentAccess.id.asc())
        .all()
    )


@router.put("/{doc_id}/access", response_model=DocumentAccessOut, status_code=status.HTTP_200_OK)
async def grant_document_access(
    doc_id: int,
    payload: DocumentAccessGrantIn,
    current_user: User = Depends(require_permission("documents:update")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not _is_company_admin(current_user) and doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    target_user = (
        db.query(User)
        .filter(User.id == payload.user_id, User.company_id == current_user.company_id)
        .first()
    )

    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    access = (
        db.query(UserDocumentAccess)
        .filter(
            UserDocumentAccess.document_id == doc.id,
            UserDocumentAccess.user_id == target_user.id,
        )
        .first()
    )

    if not access:
        access = UserDocumentAccess(
            document_id=doc.id,
            user_id=target_user.id,
            granted_by_user_id=current_user.id,
        )
        db.add(access)

    access.can_read = payload.can_read
    access.can_download = payload.can_download
    access.can_ask = payload.can_ask
    access.can_update = payload.can_update
    access.can_delete = payload.can_delete

    db.commit()
    db.refresh(access)

    return access


@router.delete("/{doc_id}/access/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_document_access(
    doc_id: int,
    user_id: int,
    current_user: User = Depends(require_permission("documents:update")),
    db: Session = Depends(get_db),
):
    doc = _get_company_document(db, doc_id, current_user)

    if not _is_company_admin(current_user) and doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    access = (
        db.query(UserDocumentAccess)
        .filter(
            UserDocumentAccess.document_id == doc.id,
            UserDocumentAccess.user_id == user_id,
        )
        .first()
    )

    if not access:
        raise HTTPException(status_code=404, detail="Access record not found")

    db.delete(access)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/{doc_id}", status_code=status.HTTP_200_OK, response_model=DocumentOut)
async def get_document(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:read")),
    db: Session = Depends(get_db),
):
    return _get_accessible_document(db, doc_id, current_user, "read")


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    current_user: User = Depends(require_permission("documents:delete")),
    db: Session = Depends(get_db),
):
    doc = _get_accessible_document(db, doc_id, current_user, "delete")

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
    _get_accessible_document(db, doc_id, current_user, "read")

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
    doc = _get_accessible_document(db, doc_id, current_user, "read")

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