from sqlalchemy import Column, DateTime, Integer, String, func

from db.base import Base


class EmbeddingConfig(Base):
    __tablename__ = "embedding_config"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(255), nullable=False)
    base_url = Column(String(512), nullable=False)
    api_key = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
