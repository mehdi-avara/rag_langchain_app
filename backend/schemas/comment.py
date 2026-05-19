from datetime import datetime
from typing import List, Optional
from fastapi import UploadFile
from pydantic import BaseModel, Field

from Models import CommentType


class CommentBase(BaseModel):
    type: CommentType = CommentType.COMMENT
    content: str
    title: str
    # media_addresses: List[str] = Field(default_factory=list)


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    type: CommentType | None = None
    content: str | None = None
    title: str | None = None



class CommentFileOut(BaseModel):
    id: int
    file_name: str
    media_address: str
    asset_id: Optional[int] = None

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
    asset_id: Optional[int] = None

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
    created_at: datetime
    files: List[CommentFileOut] = Field(default_factory=list)

    class Config:
        from_attributes = True   
