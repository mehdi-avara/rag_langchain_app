# schemas/system_tag.py
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---------- Base Schemas ----------

class SystemTagBase(BaseModel):
    tag_name: str
    description: Optional[str] = None
    father_tag_id: Optional[int] = None


class SystemTagCreate(SystemTagBase):
    """
    Used when creating a new system tag.
    - owner_id comes from current user, not from client.
    """
    pass


class SystemTagUpdate(BaseModel):
    """
    Used when updating a system tag.
    All fields are optional (partial update).
    """
    tag_name: Optional[str] = None
    description: Optional[str] = None
    father_tag_id: Optional[int] = None


# ---------- Output Schemas ----------

class SystemTagOut(BaseModel):
    id: int
    owner_id: int
    father_tag_id: Optional[int]
    tag_name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


class SystemTagTreeOut(BaseModel):
    """
    For returning the whole tree in one go (root tags with nested children).
    """
    id: int
    tag_name: str
    description: Optional[str] = None
    father_tag_id: Optional[int] = None
    children: List["SystemTagTreeOut"] = []

    class Config:
        orm_mode = True


SystemTagTreeOut.update_forward_refs()