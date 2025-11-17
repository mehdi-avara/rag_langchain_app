from pydantic import BaseModel
from datetime import datetime

class ChatAIModelOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    url: str

class ChatAIModelIn(BaseModel):
    name: str
    description: str
    is_active: bool
    url: str
    api_key: str

class ChatAIModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    url: str | None = None
    api_key: str | None = None