from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DocumentOut(BaseModel):
    id: int
    filename: str
    n_pages: int
    n_chunks: int
    created_at: datetime
    status: str
    abstract: str | None
    file_path: str | None
    original_asset_id: int | None = None
    

    class Config:
        orm_mode = True

class ChunkOut(BaseModel):
    id: int
    doc_id: int
    page_num: int
    chunk_type: str
    content: str
    start_pos: Optional[int]
    end_pos: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentAccessGrantIn(BaseModel):
    user_id: int
    can_read: bool = True
    can_download: bool = False
    can_ask: bool = True
    can_update: bool = False
    can_delete: bool = False


class DocumentAccessOut(BaseModel):
    id: int
    user_id: int
    document_id: int
    can_read: bool
    can_download: bool
    can_ask: bool
    can_update: bool
    can_delete: bool
    granted_by_user_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
