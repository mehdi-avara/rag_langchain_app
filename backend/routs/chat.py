from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from core.exceptions import chat_not_found_exception
from schemas.chat import ChatRequest, ChatResponse, ChatUpdateNameRequest, Retrieved_data, ChatListResponse, ChatListItem, ChatHistoryResponse, ChatMessageItem
from db.init_db import get_db
from deps import get_current_user
from Models import Chat, ChatMessage, User, Document, DocumentStatusType
from core.agents import build_answer_graph , GraphState, call_llm_to_rewrite
from Models.chat import ChatRole
from settings import get_settings

router = APIRouter()


def get_or_create_chat(
    db: Session,
    *,
    chat_id: int | None,
    user: User,
) -> Chat:
    if chat_id:
        chat = (
            db.query(Chat)
            .filter(Chat.id == chat_id, Chat.user_id == user.id)
            .first()
        )
        if not chat:
            raise chat_not_found_exception()
        return chat

    chat = Chat(name="New Chat", user_id=user.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def add_message(
    db: Session,
    *,
    chat_id: int,
    role: ChatRole,
    content: str,
    citations: list[int] | None = None,
    retrieved_chunks: list[dict] | None = None,
) -> ChatMessage:
    message = ChatMessage(
        chat_id=chat_id,
        role=role,
        content=content,
        citations=citations,
        retrieved_chunks=retrieved_chunks,
    )

    db.add(message)
    db.commit()
    db.refresh(message)
    return message

def build_retrieved_data(
    db: Session,
    *,
    chunks: list,
    comments: list,
) -> tuple[list[Retrieved_data], list[int]]:

    retrieved_data: list[Retrieved_data] = []
    citations: list[int] = []

    doc_ids = {c.doc_id for c in chunks}

    docs = (
        db.query(Document.id, Document.filename)
        .filter(Document.id.in_(doc_ids))
        .all()
        if doc_ids else []
    )

    doc_name_map = {d.id: d.filename for d in docs}

    for chunk in chunks:
        retrieved_data.append(
            Retrieved_data(
                content=chunk.content,
                doc_id=chunk.doc_id,
                doc_name=doc_name_map[chunk.doc_id],
                title=doc_name_map[chunk.doc_id],
                chunk_id=chunk.id,
                chunk_page=chunk.page_num + 1,
                comment_id=None,
                comment_type=None,
            )
        )
        citations.append(chunk.id)

    for comment in comments:
        retrieved_data.append(
            Retrieved_data(
                content=comment.content,
                doc_id=None,
                doc_name= "",
                title=comment.title,
                chunk_id=None,
                chunk_page=None,
                comment_id=comment.id,
                comment_type=comment.type,
            )
        )

    return retrieved_data, citations

# Chat route /chat itself
@router.post("")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ChatResponse:
    chat = get_or_create_chat(
        db,
        chat_id=request.chat_id,
        user=current_user,
    )

    add_message(
        db,
        chat_id=chat.id,
        role=ChatRole.user,
        content=request.query,
    )

    query = request.query
    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)

    route = "search" if request.preview else "full"

    graph = build_answer_graph()
    state = GraphState(
        question=query,
        route=route,
        db=db,
        mode="vector",
        doc_ids=request.doc_ids,
    )

    result = await graph.ainvoke(state)

    retrieved_data, citations = build_retrieved_data(
        db,
        chunks=result.get("chunks", []),
        comments=result.get("comments", []),
    )

    add_message(
        db,
        chat_id=chat.id,
        role=ChatRole.assistant,
        content=result["answer"],
        citations=citations,
        retrieved_chunks=[c.model_dump() for c in retrieved_data],
    )

    return {
        "answer": result["answer"],
        "citations": citations,
        "retrieved_chunks": retrieved_data,
        "chat_id": chat.id,
    }



@router.patch("/{chat_id}/name")
async def update_chat_name(
    chat_id: int,
    request: ChatUpdateNameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise chat_not_found_exception()

    chat.name = request.name
    db.commit()
    db.refresh(chat)

    return {"chat_id": chat.id, "name": chat.name}


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat = (
        db.query(Chat)
        .filter(Chat.id == chat_id, Chat.user_id == current_user.id)
        .first()
    )

    if not chat:
        raise chat_not_found_exception()

    # delete messages first
    db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).delete()
    db.delete(chat)
    db.commit()
    

@router.get("/list", response_model=ChatListResponse)
async def list_user_chats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chats = (
        db.query(Chat.id, Chat.name)
        .filter(Chat.user_id == current_user.id)
        .order_by(desc(Chat.id))  # newest first
        .all()
    )

    return ChatListResponse(
        chats=[
            ChatListItem(
                chat_id=chat.id,
                name=chat.name
                )
            for chat in chats
        ]
    )
    
    
@router.get("/{chat_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure the chat belongs to the current user
    chat = (
        db.query(Chat)
        .filter(Chat.id == chat_id, Chat.user_id == current_user.id)
        .first()
    )
    if not chat:
        raise chat_not_found_exception()

    # Load messages (oldest -> newest)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat.id)
        .order_by(desc(ChatMessage.id))
        .all()
    )

    def parse_retrieved_chunks(raw) -> List[Retrieved_data]:
        """
        raw is what you stored in DB:
        - None
        - list[dict] (from c.model_dump())
        """
        if not raw:
            return []
        # validate/convert dicts -> Retrieved_data
        return [Retrieved_data.model_validate(item) for item in raw]

    return ChatHistoryResponse(
        chat_id=chat.id,
        name=chat.name,
        messages=[
            ChatMessageItem(
                id=m.id,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                content=m.content,
                citations=m.citations or [],
                retrieved_chunks=parse_retrieved_chunks(m.retrieved_chunks),
                created_at=m.created_at,
            )
            for m in messages
        ],
    )
