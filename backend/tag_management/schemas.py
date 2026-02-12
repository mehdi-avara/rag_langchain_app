from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, root_validator
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

    @root_validator
    def validate_page_range(cls, values):
        start_page = values.get("start_page")
        end_page = values.get("end_page")
        if start_page is not None and end_page is not None and start_page > end_page:
            raise ValueError("start_page must be less than or equal to end_page")
        return values


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
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    type: CommentType
    content: str
    created_at: datetime
    note: Optional[str] = None
    linked_at: Optional[datetime] = None


TagTreeOut.update_forward_refs()
