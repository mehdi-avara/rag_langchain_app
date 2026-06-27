from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str
    chat_id: Optional[int] = None
    doc_ids: List[int] | None = None
    receipt_ids: List[int] | None = None
    rewrite_query: bool = False
    extract_keywords_with_llm: bool = False
    preview: bool = False


class RetrievedItem(BaseModel):
    resource_type: str
    source_type: str | None = None
    citation_key: str | None = None
    title: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class RetrieveInformation(BaseModel):
    items: List[RetrievedItem] = Field(default_factory=list)
    by_type: Dict[str, List[RetrievedItem]] = Field(default_factory=dict)


class Retrieved_data(RetrievedItem):
    pass


class ChatResponse(BaseModel):
    answer: str
    citations: List[Any] = Field(default_factory=list)
    retrieved_chunks: List[RetrievedItem] = Field(default_factory=list)
    retrieve_information: RetrieveInformation = Field(default_factory=RetrieveInformation)
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
    citations: List[Any] = Field(default_factory=list)
    retrieved_chunks: List[RetrievedItem] = Field(default_factory=list)
    retrieve_information: RetrieveInformation = Field(default_factory=RetrieveInformation)
    draft_id: Optional[int] = None
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    chat_id: int
    name: str
    messages: List[ChatMessageItem]
