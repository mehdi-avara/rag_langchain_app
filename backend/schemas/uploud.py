from pydantic import BaseModel
from typing import Optional

class DocumentUploadMetadata(BaseModel):
    system_tag_id: Optional[int] = 1