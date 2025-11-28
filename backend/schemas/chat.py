from typing import List
from pydantic import BaseModel

class ChatRequest(BaseModel):
    query: str
    doc_ids: List[int] | None = None
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    preview: bool = False

class Retrieved_data(BaseModel):
    content: str
    doc_id: int
    doc_name: str
    chunk_id: int | None
    chunk_page: int | None
    comment_id: int | None

class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    retrieved_chunks: List[Retrieved_data]
