from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from Models import CommentType


class CommentBase(BaseModel):
    system_tag_id: Optional[int] = 1
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    type: Optional[CommentType] = CommentType.COMMENT
    content: str
    media_addresses: List[str] = Field(default_factory=list)


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    content: str


class CommentFileOut(BaseModel):
    id: int
    media_address: str

    class Config:
        from_attributes = True


class CommentOut(BaseModel):
    id: int
    user_id: int
    system_tag_id: int
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    type: CommentType
    content: str
    created_at: datetime
    files: List[CommentFileOut] = Field(default_factory=list)

    class Config:
        from_attributes = True   

