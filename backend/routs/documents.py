from typing import List, Optional
from fastapi import Depends, APIRouter, UploadFile, status, Response , HTTPException, Query, Request, Header
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
import os

from deps import get_current_user
from Models import User,Document,Chunk,DocumentStatusType
from db.init_db import get_db
from db.search_connector import search_documents_text, search_documents_semantic
from schemas.document import DocumentOut,ChunkOut
from schemas.search import TextSearchRequest, SemanticSearchRequest
from settings import get_settings

from core.celery.tasks import mineru_process_pdf

settings = get_settings()


router = APIRouter()


@router.post("/upload")
def upload_pdf_mineru(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
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
        status=DocumentStatusType.QUEUED
    )
    db.add(doc)
    db.commit()
    
    temp_path = os.path.join(settings.files_dir, f"{doc.id}")
    os.makedirs(temp_path, exist_ok=True)
    orginal_pdf = os.path.join(temp_path, f"original.pdf")
    
    with open(orginal_pdf, "wb") as f:
        f.write(file_bytes)
    
    mineru_process_pdf.delay(
        pdf_path=os.path.join(f"{doc.id}","original.pdf"),
        doc_id=doc.id    
        )

    return {"doc_id": doc.id, "status": DocumentStatusType.QUEUED.value}

@router.get("", response_model=List[DocumentOut])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return (
    db.query(Document)
      .filter(Document.owner_id == current_user.id)
      .order_by(Document.created_at.desc())
      .all()
)


@router.post("/filter", response_model=List[DocumentOut], status_code=status.HTTP_200_OK)
async def filter_documents(
    payload: TextSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return search_documents_text(
        db=db,
        query_text=payload.query,
        owner_id=current_user.id,
        doc_ids=payload.ids or None,
        limit=payload.limit,
    )


@router.post("/semantic-search", response_model=List[DocumentOut], status_code=status.HTTP_200_OK)
async def semantic_search_documents(
    payload: SemanticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return search_documents_semantic(
        db=db,
        query_text=payload.query,
        owner_id=current_user.id,
        doc_ids=payload.ids or None,
        limit=payload.limit,
    )


@router.get("/{doc_id}", status_code=status.HTTP_200_OK, response_model=DocumentOut)
async def get_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id
    ).first()
    #TODO we should add the logic to delete the files too
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# @router.get("/summary/{doc_id}")
# async def get_summary(
#     doc_id: int,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db)
# ):
#     doc = db.query(Document).filter(
#         Document.id == doc_id,
#         Document.owner_id == current_user.id
#     ).first()
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
    
#     if not doc.abstract:
#         doc.abstract = await summarise_document(doc_id, db)
#         db.commit()
    
#     return {"abstract": doc.abstract}

@router.get("/{doc_id}/chunks", response_model=List[ChunkOut])
async def browse_chunks(
    doc_id: int,
    start_page: int = Query(1, ge=1),
    end_page: Optional[int] = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Get document
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check ownership
    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this document")

    if end_page is None:
        end_page = start_page
    if end_page < start_page:
        raise HTTPException(status_code=400, detail="end_page must be greater than or equal to start_page")

    db_start_page = start_page - 1
    db_end_page = end_page - 1

    # Get all chunks in the page range, sorted by page then chunk order.
    chunks = (
        db.query(Chunk)
          .filter(
              Chunk.doc_id == doc_id,
              Chunk.page_num >= db_start_page,
              Chunk.page_num <= db_end_page
          )
          .order_by(Chunk.page_num.asc(), Chunk.id.asc())
          .all()
    )
    
    return chunks


@router.get("/download/{doc_id}")
async def download_pdf(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download the original PDF file for a document.
    """
    
    # Get document
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check ownership
    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this document")
    
    # Check if the document has a file path
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file path found for this document")
    
    # Construct full path: FILES_DIR/{doc_id}/original.pdf
    file_path = Path(settings.files_dir) / doc.file_path / "original.pdf"
    
    # Check if file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    # Return the file for download
    return FileResponse(
        path=file_path,
        filename=doc.filename,
        media_type='application/pdf'
    )

@router.get("/chunks/{chunk_id}")
async def get_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    result = {
        "id": chunk.id,
        "doc_id": chunk.doc_id,
        "page_num": chunk.page_num,
        "start_pos": chunk.start_pos,
        "end_pos": chunk.end_pos,
        "chunk_type": chunk.chunk_type,
        "content": chunk.content,
    }
    return result

@router.get("/{doc_id}/images/{image_path:path}")
async def get_document_image(
    doc_id: int,
    image_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieve an image from a document's folder.
    The image_path should be relative to the document's 'original/auto' directory.
    Example: images/1909f77aa61d1702b3d74dab559a2781dc56ff85420b4535a7d6c29c4053373f.jpg
    """
    
    # Get document
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check ownership
    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this document")
    
    # Check if the document has a file path
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file path found for this document")
    
    # Construct full path: FILES_DIR/{doc_id}/original/auto/{image_path}
    full_image_path = Path(settings.files_dir) / doc.file_path / "original" / "auto"/ "images" / image_path
    
    # Security check: ensure the resolved path is within the expected directory
    try:
        full_image_path = full_image_path.resolve()
        expected_base = (Path(settings.files_dir) / doc.file_path / "original" / "auto").resolve()
        if not str(full_image_path).startswith(str(expected_base)):
            raise HTTPException(status_code=403, detail="Invalid image path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image path")
    
    # Check if file exists
    if not full_image_path.exists() or not full_image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    
    # Determine media type based on file extension
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
        '.bmp': 'image/bmp',
    }
    
    file_ext = full_image_path.suffix.lower()
    media_type = media_types.get(file_ext, 'application/octet-stream')
    
    # Return the image file
    return FileResponse(
        path=full_image_path,
        media_type=media_type
    )


# @router.options("/stream/{doc_id}")
# async def options_stream_pdf(doc_id: int):
#     return Response(
#         status_code=200,
#         headers={
#             "Access-Control-Allow-Origin": "*",
#             "Access-Control-Allow-Headers": "Authorization, Range, Content-Type",
#             "Access-Control-Allow-Methods": "GET, OPTIONS",
#             "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges",
#         },
#     )

@router.get("/stream/{doc_id}")
async def stream_pdf(
    request: Request,
    doc_id: int,
    Range: Optional[str] = Header(None, description="Byte range, e.g. 'bytes=0-65535'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    file_path = Path(settings.files_dir) / doc.file_path / "original.pdf"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    def iter_file(start: int, end: int):
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            chunk = 1024 * 1024  # 1MB chunks
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    if range_header:  # Client requests a byte range
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

    # If no Range header → return full file
    return StreamingResponse(
        iter_file(0, file_size - 1),
        media_type="application/pdf",
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )
