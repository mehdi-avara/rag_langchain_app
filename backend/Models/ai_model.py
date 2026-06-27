from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text

from db.base import Base


class ChatAIModels(Base):
    __tablename__ = "chat_ai_models"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, default=True)
    url = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    # Whether this chat model is vision-capable (a VLM). The assistant sends image
    # blocks to the model only when this is true; otherwise it sends extracted text
    # (PROMPT §7).
    supports_vision = Column(Boolean, nullable=False, default=False)