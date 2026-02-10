from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime


class ChatRequest(BaseModel):
    query: str
    chat_id: Optional[int] = None
    doc_ids: List[int] | None = None
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    preview: bool = False

class Retrieved_data(BaseModel):
    content: str
    doc_id: int | None
    doc_name: str
    title: str
    chunk_id: int | None
    chunk_page: int | None
    comment_id: int | None
    comment_type: str | None

class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    retrieved_chunks: List[Retrieved_data]
    chat_id: int
    
class ChatUpdateNameRequest(BaseModel):
    name: str

class ChatListItem(BaseModel):
    chat_id: int
    name: str

class ChatListResponse(BaseModel):
    chats: List[ChatListItem]
    
class ChatMessageItem(BaseModel):
    id: int
    role: str  
    content: str
    citations: List[int] = []
    retrieved_chunks: List[Retrieved_data] = []
    created_at: datetime

class ChatHistoryResponse(BaseModel):
    chat_id: int
    name: str
    messages: List[ChatMessageItem]