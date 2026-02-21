from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, model_validator
from Models import CommentType


class TagBase(BaseModel):
    tag_name: str
    description: Optional[str] = None
    father_tag_id: Optional[int] = None


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    tag_name: Optional[str] = None
    description: Optional[str] = None
    father_tag_id: Optional[int] = None


class TagOut(BaseModel):
    id: int
    owner_id: int
    father_tag_id: Optional[int]
    tag_name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


class TagTreeOut(BaseModel):
    id: int
    tag_name: str
    description: Optional[str] = None
    father_tag_id: Optional[int] = None
    children: List["TagTreeOut"] = Field(default_factory=list)

    class Config:
        orm_mode = True


class TagModelLinkCreate(BaseModel):
    model_id: int
    note: Optional[str] = None


class TagModelLinkOut(BaseModel):
    tag_id: int
    model_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class TagModelOut(BaseModel):
    id: int
    manufacturer: str
    model: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class TagDocumentOut(BaseModel):
    id: int
    filename: str
    system_tag_id: int
    n_pages: int
    n_chunks: int
    created_at: datetime
    status: str
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


class TagDocLinkCreate(BaseModel):
    document_id: int
    start_page: Optional[int] = Field(None, ge=1)
    end_page: Optional[int] = Field(None, ge=1)
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_page_range(self):
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.start_page > self.end_page
        ):
            raise ValueError("start_page must be less than or equal to end_page")
        return self


class TagDocLinkOut(BaseModel):
    tag_id: int
    document_id: int
    linked_by_user_id: int
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class TagCommentLinkCreate(BaseModel):
    comment_id: int
    note: Optional[str] = None


class TagCommentLinkOut(BaseModel):
    tag_id: int
    comment_id: int
    linked_by_user_id: int
    note: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class TagCommentOut(BaseModel):
    id: int
    user_id: int
    system_tag_id: int
    title: str
    type: CommentType
    content: str
    created_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


TagTreeOut.update_forward_refs()


class TagTextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    ids: List[int] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class TagDocumentSearchResult(BaseModel):
    id: int
    filename: str
    n_pages: int
    n_chunks: int
    created_at: datetime
    status: str
    abstract: Optional[str] = None
    file_path: Optional[str] = None

    class Config:
        from_attributes = True


class TagCommentSearchResult(BaseModel):
    id: int
    user_id: int
    title: str
    type: CommentType
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class TagContentSearchResponse(BaseModel):
    documents: List[TagDocumentSearchResult] = Field(default_factory=list)
    comments: List[TagCommentSearchResult] = Field(default_factory=list)


class TagSemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    types: List[CommentType] = Field(default_factory=list)


class TagSemanticSearchRequestWithIds(TagSemanticSearchRequest):
    ids: List[int] = Field(default_factory=list)


class TagScopeItem(TagBase):
    tag_id: int
    createdAt: datetime
    ownerId: int


class TagDocumentSemanticHit(BaseModel):
    tag_id: int
    tag_title: str
    model_id: Optional[int] = None
    model_title: Optional[str] = None
    document_id: int
    document_title: str
    part_id: int
    part_text: str
    createdAt: datetime
    status: str
    owner_id: int


class TagCommentSemanticHit(BaseModel):
    tag_id: int
    tag_title: str
    model_id: Optional[int] = None
    model_title: Optional[str] = None
    comment_id: int
    comment_title: str
    comment_content: str
    type: CommentType
    createdAt: datetime
    userId: int


class TagSemanticSearchResponse(BaseModel):
    tags: List[TagScopeItem] = Field(default_factory=list)
    documents: List[TagDocumentSemanticHit] = Field(default_factory=list)
    comments: List[TagCommentSemanticHit] = Field(default_factory=list)
    


class TagAskRequest(BaseModel):
    question: str
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    route: str = "full"
    scope: Literal["docs", "comments", "both"] = "both"
    types: List[CommentType] = Field(default_factory=list)


class TagAskMultiRequest(TagAskRequest):
    tag_ids: List[int] = Field(min_length=1)


class TagAskResponse(BaseModel):
    answer: str
    citations: List[int] = Field(default_factory=list)
    used_chunk_ids: List[int] = Field(default_factory=list)
    used_comment_ids: List[int] = Field(default_factory=list)
    references: TagSemanticSearchResponse
