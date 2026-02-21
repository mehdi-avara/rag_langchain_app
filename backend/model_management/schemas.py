from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from Models import CommentType
from schemas.search import ModelSemanticSearchResponse


class ModelCreate(BaseModel):
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None


class ModelUpdate(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None


class ModelOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime
    doc_ids: List[int] = Field(default_factory=list)
    comment_ids: List[int] = Field(default_factory=list)

    class Config:
        orm_mode = True


class ModelListOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ModelDocLinkCreate(BaseModel):
    document_id: int
    note: Optional[str] = None


class ModelCommentLinkCreate(BaseModel):
    comment_id: int
    note: Optional[str] = None


class ModelDocLinkOut(BaseModel):
    model_id: int
    document_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ModelCommentLinkOut(BaseModel):
    model_id: int
    comment_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ModelDocumentOut(BaseModel):
    id: int
    filename: str
    n_pages: int
    n_chunks: int
    created_at: datetime
    status: str
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class ModelCommentOut(BaseModel):
    id: int
    user_id: int
    title: str
    type: CommentType
    content: str
    created_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class ModelAskRequest(BaseModel):
    question: str
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    route: str = "full"
    scope: Literal["docs", "comments", "both"] = "both"
    types: List[CommentType] = Field(default_factory=list)


class ModelAskMultiRequest(ModelAskRequest):
    model_ids: List[int] = Field(default_factory=list)


class ModelAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_chunk_ids: List[int] = Field(default_factory=list)
    used_comment_ids: List[int] = Field(default_factory=list)
    references: ModelSemanticSearchResponse
