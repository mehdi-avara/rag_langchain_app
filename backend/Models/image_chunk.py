from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship

from db.base import Base


class ImageChunk(Base):
    __tablename__ = "image_chunks"

    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    image_data = Column(Text, nullable=False)
    caption = Column(Text, nullable=False)
    position = Column(String, nullable=False)

    chunk = relationship("Chunk", back_populates="image_data")
    