from fastapi import FastAPI, Depends, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os

from Models import User, Document
from db.init_db import get_db
from deps import get_current_user
from core.simple_ingestion import  run_mineru_on_file
from core.agents import build_answer_graph , GraphState, call_llm_to_rewrite
from schemas.chat import ChatRequest,ChatResponse, Retrieved_data
from settings import get_settings


from routs.auth import router as auth_router
from routs.documents import router as document_router
from routs.comment import router as comment_router
from routs.users import router as user_router
from routs.chat_ai_models import router as chat_ai_models_router


settings = get_settings()


app = FastAPI(title="Porsa Search system")

# CORS middleware
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://porsa.javidanparto.com", 
        "https://porsa.javidanparto.com",   
        "http://localhost:5000"  # allow all origins for testing purposes
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



app.include_router(auth_router,prefix="/auth",tags=["Auth"])
app.include_router(document_router,prefix="/documents",tags=["document"])
app.include_router(comment_router, prefix="/comments", tags=["comments"])
app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(chat_ai_models_router, prefix="/llm", tags=["llm"])


@app.post("/upload")
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
        # status="queued",
    )
    db.add(doc)
    db.commit()
    
    os.makedirs(settings.files_dir, exist_ok=True)
    temp_path = os.path.join(settings.files_dir, f"{doc.id}_{file.filename}")
    with open(temp_path, "wb") as f:
        f.write(file_bytes)

    run_mineru_on_file(
        pdf_path=temp_path,
        filename=file.filename,
        doc_id=doc.id    
        )

    return {"doc_id": doc.id, "status": "queued"}

# Chat route
@app.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ChatResponse:
    query = request.query
    
    # Query rewriting if requested
    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)
    route = "full"
    if request.preview == True:
        route = "search"
    answer_graph = build_answer_graph()
    
    state_graph = GraphState(
        question=query,
        route=route,  
        db=db,  # Pass the database session
        mode="vector",
        doc_ids=request.doc_ids
    )
    result = await answer_graph.ainvoke(state_graph)
    answer = result["answer"]
    retrieved_data = []
    citations = []
    # Fetch all needed doc_ids first to avoid multiple queries
    doc_ids = {chunk.doc_id for chunk in result["chunks"]}
    doc_ids |= {comment.doc_id for comment in result.get("comments", [])}

    # Query all documents in one go (better performance)
    docs = db.query(Document.id, Document.filename).filter(Document.id.in_(doc_ids)).all()
    doc_map = {doc.id: doc.filename for doc in docs}

    for chunk in result["chunks"]:
        retrieved_data.append(Retrieved_data(
            content=chunk.content,
            doc_id=chunk.doc_id,
            doc_name=doc_map.get(chunk.doc_id),
            chunk_id=chunk.id,
            chunk_page=chunk.page_num + 1,
            comment_id=None
        ))
        citations.append(chunk.id)
          
    for comments in result.get("comments", []):
        retrieved_data.append(Retrieved_data(
            content=comments.content,
            doc_id=comments.doc_id,
            doc_name=doc_map.get(chunk.doc_id),
            chunk_id=comments.chunk_id,
            chunk_page=None,
            comment_id=comments.id
        ))

    return {"answer": answer, "citations": citations, "retrieved_chunks": retrieved_data}

