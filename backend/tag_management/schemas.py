from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


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
    children: List["TagTreeOut"] = []

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


TagTreeOut.update_forward_refs()
