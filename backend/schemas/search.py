from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from schemas.document import DocumentOut
from schemas.comment import CommentOut
from Models import CommentType


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class DocumentSemanticHit(BaseModel):
    document_id: int
    document_title: str
    part_id: int
    part_text: str
    createdAt: datetime
    status: str
    owner_id: int


class CommentSemanticHit(BaseModel):
    comment_id: int
    comment_title: str
    comment_content: str
    type: CommentType
    createdAt: datetime
    userId: int


class TagDocumentSemanticHit(DocumentSemanticHit):
    tag_id: int
    tag_title: str
    model_id: Optional[int] = None
    model_title: Optional[str] = None


class TagCommentSemanticHit(CommentSemanticHit):
    tag_id: int
    tag_title: str
    model_id: Optional[int] = None
    model_title: Optional[str] = None


class ModelDocumentSemanticHit(DocumentSemanticHit):
    model_id: Optional[int] = None
    model_title: Optional[str] = None


class ModelCommentSemanticHit(CommentSemanticHit):
    model_id: Optional[int] = None
    model_title: Optional[str] = None


class SemanticCommentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    types: List[CommentType] = Field(default_factory=list)

class SemanticCommentSearchRequestWithId(SemanticCommentSearchRequest):
    pass

class TagSemanticSearchResponse(BaseModel):
    documents: List[TagDocumentSemanticHit] = Field(default_factory=list)
    comments: List[TagCommentSemanticHit] = Field(default_factory=list)


class ModelSemanticSearchResponse(BaseModel):
    documents: List[ModelDocumentSemanticHit] = Field(default_factory=list)
    comments: List[ModelCommentSemanticHit] = Field(default_factory=list)


class ContentSearchResponse(BaseModel):
    documents: List[DocumentOut] = Field(default_factory=list)
    comments: List[CommentOut] = Field(default_factory=list)




SearchMode = Literal["keyword", "semantic", "vector", "hybrid"]
SearchScope = Literal["docs", "comments", "both"]


class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    mode: SearchMode = "hybrid"
    limit: int = Field(default=50, ge=1, le=200)


class DocumentSearchResponse(BaseModel):
    mode: SearchMode
    documents: List[DocumentOut] = Field(default_factory=list)
    hits: List[DocumentSemanticHit] = Field(default_factory=list)


class CommentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    types: List[CommentType] = Field(default_factory=list)
    mode: SearchMode = "hybrid"
    limit: int = Field(default=50, ge=1, le=200)


class CommentSearchResponse(BaseModel):
    mode: SearchMode
    comments: List[CommentOut] = Field(default_factory=list)
    hits: List[CommentSemanticHit] = Field(default_factory=list)


class DocumentAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    scope: Literal["docs", "comments", "both"] = "both"


class DocumentAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_chunk_ids: List[int] = Field(default_factory=list)
    used_comment_ids: List[int] = Field(default_factory=list)
    references: List[DocumentSemanticHit] = Field(default_factory=list)


class CommentAskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    scope: Literal["docs", "comments", "both"] = "both"
    types: List[CommentType] = Field(default_factory=list)


class CommentAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_chunk_ids: List[int] = Field(default_factory=list)
    used_comment_ids: List[int] = Field(default_factory=list)
    references: List[CommentSemanticHit] = Field(default_factory=list)
