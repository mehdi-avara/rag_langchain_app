from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from openai import AsyncOpenAI


from db.models import User, Document, Chunk
from db.init_db import get_db
from deps import get_current_user
from core.ingestion import  ingest_pdf_as_single_document
from core.simple_ingestion import  ingest_file
from core.agents.langgraph import build_answer_graph
from core.chunking  import ChunkingMode
from settings import get_settings

from routs.auth import router as auth_router
from routs.documents import router as document_router

settings = get_settings()
aclient = AsyncOpenAI(api_key=settings.openai_api_key)

app = FastAPI(title="RAG API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class ChatRequest(BaseModel):
    query: str

class UploadRequest(BaseModel):
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed

class QueryRequest(BaseModel):
    query: str
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    # chunking_mode: ChunkingMode = ChunkingMode.token_fixed


app.include_router(auth_router,prefix="/auth",tags=["Auth"])
app.include_router(document_router,prefix="/documents",tags=["document"])


# Document routes
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    doc_id = await ingest_file(contents, file.filename, current_user.id, db, chunking_mode)
    return {"doc_id": doc_id}

@app.post("/upload-md-zip")
async def upload_md_file(
    file: UploadFile = File(...),
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a markdown file and process it."""
    
    if not file.filename.lower().endswith('.zip'):
        pass
                
    contents = await file.read()
    doc_id = await ingest_file(contents, file.filename, current_user.id, db, chunking_mode)
    return {"doc_id": doc_id}


@app.post("/upload-pdf-as-images")
async def upload_pdf_as_images(
    file: UploadFile,
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a PDF file and process it as images."""

    # Read file content
    file_bytes = await file.read()
    
    # Validate PDF file
    if not file_bytes.startswith(b'%PDF'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
        
    # Validate file extension
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must have .pdf extension")
    
# Use the new ingestion function
    doc_id = await ingest_pdf_as_single_document(
        file_bytes=file_bytes,
        filename=file.filename,
        user_id=current_user.id,
        db=db,
        chunking_mode=chunking_mode
    )
    return {"message": "PDF processed successfully", "doc_id": doc_id}


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
        "user_id": current_user.id,
        "db": db,  # Pass the database session
    })
    return result

@app.post("/query/preview")
async def query_docs(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = request.query
    
    # Query rewriting if requested
    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)
    


    # Build answer graph with specified chunking mode
    answer_graph = build_answer_graph()
    result = await answer_graph.ainvoke({
        "question": query,
        "keywords": query,
        "route": "hybrid",
        # "chunking_mode": request.chunking_mode,
        "user_id": current_user.id,
        "mode": "hybrid",
        "db": db
    })

    # Transform LangChain Document objects into dictionaries
    retrieved_chunks = []
    for doc in result["docs"]:
        retrieved_chunks.append({
            "content": doc.page_content,
            "page_num": doc.metadata.get("page_num", "N/A"),
            "doc_id": doc.metadata.get("doc_id", None),
        })

    return {"retrieved_chunks": retrieved_chunks}

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


async def call_llm_to_rewrite(query: str) -> str:
    """Use LLM to improve the query for better search performance."""
    response = await aclient.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that improves search queries. Make the query more specific and effective for information retrieval while preserving the original intent."
            },
            {
                "role": "user",
                "content": f"Improve this search query: {query}"
            }
        ],
        max_tokens=150
    )
    return response.choices[0].message.content

async def call_llm_to_extract_keywords(query: str) -> List[str]:
    """Use LLM to extract keywords from the query."""
    response = await aclient.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant that extracts key terms from queries. Return only the most important keywords or phrases, separated by commas."
            },
            {
                "role": "user",
                "content": f"Extract key terms from this query: {query}"
            }
        ],
        max_tokens=100
    )
    keywords = response.choices[0].message.content.split(',')
    return [k.strip() for k in keywords if k.strip()]

def basic_keyword_extraction(query: str) -> List[str]:
    """Basic keyword extraction using simple heuristics."""
    # Remove common stop words and punctuation
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'about', 'as'}
    words = query.lower().split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return keywords 