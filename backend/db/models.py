from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import uuid
from pydantic import BaseModel

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    pw_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    n_pages = Column(Integer, nullable=False)
    n_chunks = Column(Integer, nullable=False)
    abstract = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship("User", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    page_num = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    vdb_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    es_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    start_pos = Column(Integer, nullable=True)  # Starting position in the document
    end_pos = Column(Integer, nullable=True)    # Ending position in the document
    chunk_type = Column(String, nullable=True, default="text")  # "text" or "image"

    document = relationship("Document", back_populates="chunks")


class ImageChunk(Base):
    __tablename__ = "image_chunks"

    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False)
    image_data = Column(Text, nullable=False)  # Base64 encoded image data
    caption = Column(Text, nullable=False)     # Image caption/description
    position = Column(String, nullable=False)  # Position on page (e.g., "top-left", "center", etc.)
    
    chunk = relationship("Chunk", backref="image_data")


class LoginRequest(BaseModel):
    username: str
    password: str