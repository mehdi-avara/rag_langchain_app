from typing import List
from fastapi import Depends, APIRouter, status, Response , HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path


from db.models import User,Document,Chunk
from db.init_db import get_db
from core.summarise import summarise_document
from schemas.document import DocumentOut,ChunkOut
from deps import get_current_user
from settings import get_settings

settings = get_settings()


router = APIRouter()
@router.get("/", response_model=List[DocumentOut])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Document).filter(Document.owner_id == current_user.id).all()



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
    from retrieval.vector.postgres_store import PostgresVectorStore
    chat_store = PostgresVectorStore(db)
    chat_store.delete_by_doc_id(doc_id)
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary/{doc_id}")
async def get_summary(
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
    
    if not doc.abstract:
        doc.abstract = await summarise_document(doc_id, db)
        db.commit()
    
    return {"abstract": doc.abstract}


@router.get("/{doc_id}/chunks/", response_model=List[ChunkOut])
async def browse_chunks(
    doc_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
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
    
    # Calculate offset
    offset = (page - 1) * page_size
    
    # Get chunks with pagination
    chunks = db.query(Chunk)\
        .filter(Chunk.doc_id == doc_id)\
        .order_by(Chunk.page_num, Chunk.start_pos)\
        .offset(offset)\
        .limit(page_size)\
        .all()
    
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
    full_image_path = Path(settings.files_dir) / doc.file_path / "original" / "auto" / image_path
    
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
