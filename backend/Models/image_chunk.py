from sqlalchemy import Column, Integer, String, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base


class ImageChunk(Base):
    """A figure (image/table) extracted by MinerU, linked to the chunk it belongs to.

    Repurposed from the original (unused) shape: the figure now references a
    durable S3 object via ``storage_key`` instead of holding inline data. See
    docs/MINERU_S3_AND_CHUNK_IMAGES_PLAN.md.
    """

    __tablename__ = "image_chunks"
    __table_args__ = (
        Index("ix_image_chunks_chunk_id", "chunk_id"),
    )

    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String, nullable=True)
    caption = Column(Text, nullable=True)
    page_num = Column(Integer, nullable=True)
    position = Column(String, nullable=True)
    bbox = Column(JSONB, nullable=True)

    chunk = relationship("Chunk", back_populates="image_data")
