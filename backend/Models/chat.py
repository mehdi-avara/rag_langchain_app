from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum as SAEnum, JSON, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from db.base import Base
from enum import Enum

class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_company_id", "company_id"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    
    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete")

class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"
    
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)

    role = Column(
        SAEnum(ChatRole, name="chat_role_enum"),
        nullable=False,
    )
    
    content = Column(String, nullable=False)

    citations = Column(JSON, nullable=True)
    retrieved_chunks = Column(JSON, nullable=True)

    # When an assistant turn produced a Draft, the frontend re-renders the draft
    # card from history via this reference (PROMPT §8.1).
    draft_id = Column(Integer, ForeignKey("assistant_drafts.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("Chat", back_populates="messages")
     