from typing import List
from fastapi import FastAPI, Depends, HTTPException, UploadFile,Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os

from Models import User, Document, DocumentStatusType, SystemTag

from db.init_db import get_db
from deps import get_current_user
from core.celery.tasks import mineru_process_pdf
from core.agents import build_answer_graph , GraphState, call_llm_to_rewrite
from schemas.chat import ChatRequest,ChatResponse, Retrieved_data
from settings import get_settings

from routs import (
    auth_router,
    document_router,
    comment_router,
    user_router,
    chat_ai_models_router,
    system_tag_router,
    chat_router,
)

settings = get_settings()


app = FastAPI(title="Porsa Search system")

# CORS middleware
from fastapi.middleware.cors import CORSMiddleware
from middlewares.logging import LoggingMiddleware

app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)



app.include_router(auth_router,prefix="/auth",tags=["Auth"])
app.include_router(document_router,prefix="/documents",tags=["document"])
app.include_router(comment_router, prefix="/comments", tags=["comments"])
app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(chat_ai_models_router, prefix="/llm", tags=["llm"])
app.include_router(system_tag_router, prefix="/system_tags", tags=["system_tags"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])



@app.post("/upload")
def upload_pdf_mineru(
    file: UploadFile,
    system_tag_id: int,
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
        system_tag_id=system_tag_id,
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