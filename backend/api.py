from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from passlib.hash import bcrypt  
import io
from pdf2image import convert_from_bytes


from db.models import User, Document, Chunk
from db.init_db import get_db
from deps import get_current_user, create_access_token
from core.ingestion import ingest_file
from core.summarise import summarise_document
from core.graph import build_answer_graph
from db.models import LoginRequest

app = FastAPI(title="RAG API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DocumentOut(BaseModel):
    id: int
    filename: str
    n_pages: int
    n_chunks: int
    created_at: datetime
    abstract: str | None

    class Config:
        orm_mode = True

class ChunkSource(BaseModel):
    doc_id: int
    filename: str
    page_num: int
    chunk_type: str
    position: str | None
    start_pos: int | None
    end_pos: int | None

class AnswerResponse(BaseModel):
    answer: str
    sources: List[ChunkSource]
    confidence: float

class ChunkOut(BaseModel):
    id: int
    doc_id: int
    page_num: int
    chunk_type: str
    content: str
    start_pos: Optional[int]
    end_pos: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    query: str

# Auth routes
@app.post("/auth/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username
    password = payload.password
    user = db.query(User).filter(User.username == username).first()
    if not user:  # In production, use proper password hashing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    if not bcrypt.verify(password, user.pw_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    return {"access_token": create_access_token(user.id)}

# Document routes
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    doc_id = await ingest_file(contents, file.filename, current_user.id, db)
    return {"doc_id": doc_id}

@app.post("/upload-pdf-as-images")
async def upload_pdf_as_images(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    if not contents.startswith(b'%PDF'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    # Convert PDF to images
    images = convert_from_bytes(contents)
    doc_id = None
    
    for i, image in enumerate(images):
        # Convert image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        # Create filename for this page
        page_filename = f"{file.filename}_page_{i+1}.png"
        
        # Ingest the image
        if i == 0:
            doc_id = await ingest_file(img_byte_arr, page_filename, current_user.id, db)
        else:
            await ingest_file(img_byte_arr, page_filename, current_user.id, db)
    
    return {"doc_id": doc_id}

@app.get("/documents", response_model=List[DocumentOut])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Document).filter(Document.owner_id == current_user.id).all()

@app.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
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
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/summary/{doc_id}")
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

# Chat route
@app.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    answer_graph = build_answer_graph()
    result = await answer_graph.ainvoke({
        "question": request.query,
        "route": "hybrid",  # Default to hybrid search
        "user_id": current_user.id
    })
    return result

@app.get("/answer/{doc_id}")
async def get_answer(
    doc_id: int,
    question: str,
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
    
    # Get answer and sources
    answer, sources, confidence = await build_answer_graph(doc_id, question, db)
    
    # Format sources
    formatted_sources = []
    for source in sources:
        chunk = db.query(Chunk).filter(Chunk.id == source["chunk_id"]).first()
        if chunk:
            formatted_sources.append(ChunkSource(
                doc_id=doc.id,
                filename=doc.filename,
                page_num=chunk.page_num,
                chunk_type=chunk.chunk_type,
                position=chunk.start_pos if chunk.chunk_type == "text" else None,
                start_pos=chunk.start_pos,
                end_pos=chunk.end_pos
            ))
    
    return AnswerResponse(
        answer=answer,
        sources=formatted_sources,
        confidence=confidence
    ) 

@app.get("/documents/{doc_id}/chunks", response_model=List[ChunkOut])
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