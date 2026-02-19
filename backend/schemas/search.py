from typing import List

from pydantic import BaseModel, Field

from schemas.document import DocumentOut
from schemas.comment import CommentOut


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    type: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ContentSearchResponse(BaseModel):
    documents: List[DocumentOut] = Field(default_factory=list)
    comments: List[CommentOut] = Field(default_factory=list)
