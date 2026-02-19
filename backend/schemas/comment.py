from datetime import datetime
from typing import List, Optional
from fastapi import UploadFile
from pydantic import BaseModel, Field

from Models import CommentType


class CommentBase(BaseModel):
    type: CommentType = CommentType.COMMENT
    content: str
    title: str = "unknown"
    media_addresses: List[str] = Field(default_factory=list)


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    content: str


class CommentFileOut(BaseModel):
    id: int
    file_name: str
    media_address: str

    class Config:
        from_attributes = True


class CommentFileUpload(BaseModel):
    file: UploadFile
    index: bool = False
    class Config:
        arbitrary_types_allowed = True


class CommentFileName(BaseModel):
    id: int
    file_name: str

    class Config:
        from_attributes = True


class CommentOut(BaseModel):
    id: int
    user_id: int
    title: str
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    type: CommentType
    content: str
    part_id: int | None = None
    part_text: str | None = None
    similarity: float | None = None
    tag_ids: List[int] = Field(default_factory=list)
    created_at: datetime
    files: List[CommentFileOut] = Field(default_factory=list)

    class Config:
        from_attributes = True   
