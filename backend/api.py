from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from pydantic import BaseModel

from .db.models import User, Document
from .db.init_db import get_db
from .deps import get_current_user, create_access_token
from .core.ingestion import ingest_file
from .core.summarise import summarise_document
from .core.graph import build_answer_graph

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

# Auth routes
@app.post("/auth/login")
async def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.pw_hash == password:  # In production, use proper password hashing
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
    query: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    answer_graph = build_answer_graph()
    result = await answer_graph.ainvoke({
        "question": query,
        "user_id": current_user.id
    })
    return result 