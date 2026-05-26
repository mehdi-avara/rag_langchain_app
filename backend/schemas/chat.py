from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    chat_id: Optional[int] = None
    doc_ids: List[int] | None = None
    receipt_ids: List[int] | None = None
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    preview: bool = False


class Retrieved_data(BaseModel):
    content: str
    source_type: Optional[str] = None
    doc_id: int | None = None
    doc_name: str = ""
    title: str = ""
    chunk_id: int | None = None
    chunk_page: int | None = None
    comment_id: int | None = None
    comment_type: str | None = None
    receipt_id: int | None = None
    receipt_amount: str | None = None
    receipt_direction: str | None = None
    receipt_counterparty_name: str | None = None
    receipt_date: str | None = None
    receipt_tracking_number: str | None = None
    receipt_card_title: str | None = None


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
