from typing import List, Optional

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


class CommentSemanticHit(BaseModel):
    comment_id: int
    comment_title: str
    comment_content: str


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
    types: List[CommentType] = Field(default_factory=list)

class SemanticCommentSearchRequestWithId(SemanticCommentSearchRequest):
    ids: List[int] = Field(default_factory=list)

class TagSemanticSearchResponse(BaseModel):
    documents: List[TagDocumentSemanticHit] = Field(default_factory=list)
    comments: List[TagCommentSemanticHit] = Field(default_factory=list)


class ModelSemanticSearchResponse(BaseModel):
    documents: List[ModelDocumentSemanticHit] = Field(default_factory=list)
    comments: List[ModelCommentSemanticHit] = Field(default_factory=list)


class ContentSearchResponse(BaseModel):
    documents: List[DocumentOut] = Field(default_factory=list)
    comments: List[CommentOut] = Field(default_factory=list)
