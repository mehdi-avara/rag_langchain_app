from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AdminAuditLogOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    company_id: int
    actor_user_id: int | None
    action: str
    target_type: str
    target_id: str
    details_json: dict[str, Any]
    created_at: datetime
