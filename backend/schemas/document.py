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
