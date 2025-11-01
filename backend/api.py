from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from openai import AsyncOpenAI

from db.models import User
from db.init_db import get_db
from deps import get_current_user
from core.simple_ingestion import  ingest_file, ingest_pdf_with_mineru
from core.agents.langgraph import build_answer_graph , GraphState
from core.chunking  import ChunkingMode
from settings import get_settings

from routs.auth import router as auth_router
from routs.documents import router as document_router

settings = get_settings()

aclient = AsyncOpenAI(api_key=settings.openai_api_key,base_url=settings.openai_base_url)

app = FastAPI(title="Porsa Search system")

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
    doc_ids: List[int] | None = None
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False

class UploadRequest(BaseModel):
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed

class QueryRequest(BaseModel):
    query: str
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    doc_ids: List[int] | None = None
    # chunking_mode: ChunkingMode = ChunkingMode.token_fixed

class ChunkePageRequest(BaseModel):
    chunks: List[ChunkSource]

app.include_router(auth_router,prefix="/auth",tags=["Auth"])
app.include_router(document_router,prefix="/documents",tags=["document"])


@app.post("/upload-md-file")
async def upload_md_file(
    file: UploadFile = File(...),
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a markdown file and process it."""
    
    if not file.filename.lower().endswith('.md'):
        pass
                
    contents = await file.read()
    doc_id = await ingest_file(contents, file.filename, current_user.id, db, chunking_mode)
    return {"doc_id": doc_id}



@app.post("/upload")
async def upload_pdf_mineru(
    file: UploadFile,
    chunking_mode: ChunkingMode = ChunkingMode.token_fixed,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a PDF file and process it with MinerU."""
    
    # Read file content
    file_bytes = await file.read()
    
    # Validate PDF file
    if not file_bytes.startswith(b'%PDF'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
        
    # Validate file extension
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must have .pdf extension")
    
    try:
        # Use the new MinerU ingestion function
        doc_id = await ingest_pdf_with_mineru(
            pdf_bytes=file_bytes,
            filename=file.filename,
            user_id=current_user.id,
            db=db,
            chunking_mode=chunking_mode
        )
        return {"doc_id": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF with MinerU: {str(e)}")


# Chat route
@app.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = request.query
    
    # Query rewriting if requested
    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)
    
    answer_graph = build_answer_graph()
    
    state_graph = GraphState(
        question=query,
        route="full",  # Default to hybrid search
        db=db,  # Pass the database session
        mode="vector",
        doc_ids=request.doc_ids
    )
    result = await answer_graph.ainvoke(state_graph)
    answer = result["answer"]
    retrieved_chunks = []
    citations = []
    for chunk in result["chunks"]:
        retrieved_chunks.append({
            "content": chunk.content,
            "doc_id": chunk.doc_id,
            "chunk_id": chunk.id,
        })
        citations.append(chunk.id)
    return {"answer": answer, "citations": citations, "retrieved_chunks": retrieved_chunks}

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
        "route": "search",
        # "chunking_mode": request.chunking_mode,
        "mode": "vector",
        "db": db,
        "doc_ids": request.doc_ids
    })

    # Transform LangChain Document objects into dictionaries
    retrieved_chunks = []
    for chunk in result["chunks"]:
        retrieved_chunks.append({
            "content": chunk.content,
            "doc_id": chunk.doc_id,
            "chunk_id": chunk.id,
        })

    return {"retrieved_chunks": retrieved_chunks}

# @app.post("/chunks/page_numbers")
async def get_chunks_page_numbers(
    request: ChunkePageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
    ) -> List[ChunkSource]:
    """Retrieve page numbers for chunks based on their document IDs."""
    chunks = request.chunks
    chunks = find_chunk_page_numbers(chunks)
    return chunks

def find_chunk_page_numbers(chunks: List[ChunkSource]) -> List[ChunkSource]:
    """Retrieve page numbers for chunks based on their document IDs."""
    for chunk in chunks:
        # Logic to determine page number based on chunk.doc_id and chunk.position
        # This is a placeholder; actual implementation will depend on how documents and chunks are stored
        chunk.page_num = 1  # Replace with actual page number retrieval logic
    return chunks

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