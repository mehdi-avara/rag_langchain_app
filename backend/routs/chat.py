from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List

from core.exceptions import chat_not_found_exception
from schemas.chat import ChatRequest, ChatResponse, ChatUpdateNameRequest, Retrieved_data, ChatListResponse, ChatListItem, ChatHistoryResponse, ChatMessageItem
from db.init_db import get_db
from deps import require_permission
from Models import Chat, ChatMessage, User, Document, Comment
from core.agents import build_answer_graph, GraphState, call_llm_to_rewrite
from Models.chat import ChatRole
from core.celery.tasks import chat_generate_title
from routs.documents import _get_accessible_document_ids

router = APIRouter()


def get_or_create_chat(
    db: Session,
    *,
    chat_id: int | None,
    user: User,
) -> tuple[Chat, bool]:
    if user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")

    if chat_id:
        chat = (
            db.query(Chat)
            .filter(
                Chat.id == chat_id,
                Chat.company_id == user.company_id,
                Chat.user_id == user.id,
            )
            .first()
        )
        if not chat:
            raise chat_not_found_exception()
        return chat, False

    chat = Chat(name="New Chat", company_id=user.company_id, user_id=user.id)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat, True


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


def _intersect_requested_ids(
    allowed_ids: list[int] | None,
    requested_ids: list[int] | None,
) -> list[int] | None:
    if allowed_ids is None:
        return requested_ids

    if requested_ids is None:
        return allowed_ids

    allowed_set = set(allowed_ids)
    return [item_id for item_id in requested_ids if item_id in allowed_set]


def _get_current_user_comment_ids(db: Session, current_user: User) -> list[int]:
    return [
        row[0]
        for row in db.query(Comment.id)
        .filter(Comment.user_id == current_user.id)
        .all()
    ]


def build_retrieved_data(
    db: Session,
    *,
    chunks: list,
    comments: list,
    receipts: list,
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
                source_type="document_chunk",
                doc_id=chunk.doc_id,
                doc_name=doc_name_map.get(chunk.doc_id, ""),
                title=doc_name_map.get(chunk.doc_id, ""),
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
                source_type="comment",
                doc_id=None,
                doc_name="",
                title=comment.title,
                chunk_id=None,
                chunk_page=None,
                comment_id=comment.id,
                comment_type=comment.type,
            )
        )

    for receipt in receipts:
        receipt_id = receipt.get("receipt_id")
        retrieved_data.append(
            Retrieved_data(
                content=receipt.get("description") or "",
                source_type="financial_receipt",
                doc_id=None,
                doc_name="",
                title=f"Receipt #{receipt_id}",
                chunk_id=None,
                chunk_page=None,
                comment_id=None,
                comment_type=None,
                receipt_id=receipt_id,
                receipt_amount=str(receipt.get("amount")) if receipt.get("amount") is not None else None,
                receipt_direction=str(receipt.get("direction")) if receipt.get("direction") is not None else None,
                receipt_counterparty_name=receipt.get("counterparty_name"),
                receipt_date=str(receipt.get("receipt_date")) if receipt.get("receipt_date") is not None else None,
                receipt_tracking_number=receipt.get("tracking_number"),
                receipt_card_title=receipt.get("card_title"),
            )
        )

    return retrieved_data, citations


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(require_permission("chat:use")),
    db: Session = Depends(get_db),
) -> ChatResponse:
    chat_obj, is_new_chat = get_or_create_chat(
        db,
        chat_id=request.chat_id,
        user=current_user,
    )

    add_message(
        db,
        chat_id=chat_obj.id,
        role=ChatRole.user,
        content=request.query,
    )

    if is_new_chat:
        chat_generate_title.delay(chat_obj.id, request.query)

    query = request.query

    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)

    route = "search" if request.preview else "full"

    if current_user.company_id is None:
        raise HTTPException(status_code=403, detail="User has no company")

    allowed_doc_ids = _get_accessible_document_ids(db, current_user, "ask")
    safe_doc_ids = _intersect_requested_ids(allowed_doc_ids, request.doc_ids)
    safe_comment_ids = _get_current_user_comment_ids(db, current_user)

    graph = build_answer_graph()
    state = GraphState(
        question=query,
        route=route,
        db=db,
        mode="vector",
        doc_ids=safe_doc_ids,
        comment_ids=safe_comment_ids,
        company_id=current_user.company_id,
        receipt_ids=request.receipt_ids,
        scope="both",
    )

    result = await graph.ainvoke(state)

    retrieved_data, citations = build_retrieved_data(
        db,
        chunks=result.get("chunks", []),
        comments=result.get("comments", []),
        receipts=result.get("receipts", []),
    )

    answer = result.get("answer") or ""

    if not request.preview:
        add_message(
            db,
            chat_id=chat_obj.id,
            role=ChatRole.assistant,
            content=answer,
            citations=citations,
            retrieved_chunks=[c.model_dump() for c in retrieved_data],
        )

    return ChatResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=retrieved_data,
        chat_id=chat_obj.id,
    )


@router.patch("/{chat_id}/name")
async def update_chat_name(
    chat_id: int,
    request: ChatUpdateNameRequest,
    current_user: User = Depends(require_permission("chat:update")),
    db: Session = Depends(get_db),
):
    chat_obj = (
        db.query(Chat)
        .filter(
            Chat.id == chat_id,
            Chat.company_id == current_user.company_id,
            Chat.user_id == current_user.id,
        )
        .first()
    )

    if not chat_obj:
        raise chat_not_found_exception()

    chat_obj.name = request.name

    db.commit()
    db.refresh(chat_obj)

    return {"chat_id": chat_obj.id, "name": chat_obj.name}


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: int,
    current_user: User = Depends(require_permission("chat:delete")),
    db: Session = Depends(get_db),
):
    chat_obj = (
        db.query(Chat)
        .filter(
            Chat.id == chat_id,
            Chat.company_id == current_user.company_id,
            Chat.user_id == current_user.id,
        )
        .first()
    )

    if not chat_obj:
        raise chat_not_found_exception()

    db.query(ChatMessage).filter(ChatMessage.chat_id == chat_obj.id).delete()
    db.delete(chat_obj)
    db.commit()


@router.get("/list", response_model=ChatListResponse)
async def list_user_chats(
    current_user: User = Depends(require_permission("chat:read")),
    db: Session = Depends(get_db),
):
    chats = (
        db.query(Chat.id, Chat.name)
        .filter(
            Chat.company_id == current_user.company_id,
            Chat.user_id == current_user.id,
        )
        .order_by(desc(Chat.id))
        .all()
    )

    return ChatListResponse(
        chats=[
            ChatListItem(
                chat_id=chat.id,
                name=chat.name,
            )
            for chat in chats
        ]
    )


@router.get("/{chat_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    chat_id: int,
    current_user: User = Depends(require_permission("chat:read")),
    db: Session = Depends(get_db),
):
    chat_obj = (
        db.query(Chat)
        .filter(
            Chat.id == chat_id,
            Chat.company_id == current_user.company_id,
            Chat.user_id == current_user.id,
        )
        .first()
    )

    if not chat_obj:
        raise chat_not_found_exception()

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_obj.id)
        .order_by(desc(ChatMessage.id))
        .all()
    )

    def parse_retrieved_chunks(raw) -> List[Retrieved_data]:
        if not raw:
            return []
        return [Retrieved_data.model_validate(item) for item in raw]

    return ChatHistoryResponse(
        chat_id=chat_obj.id,
        name=chat_obj.name,
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