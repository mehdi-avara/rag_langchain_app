from __future__ import annotations

from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from core.agents import GraphState, build_answer_graph, call_llm_to_rewrite
from core.celery.tasks import chat_generate_title
from core.exceptions import chat_not_found_exception
from db.init_db import get_db
from deps import require_permission
from financial_management.models import FinancialReceipt
from financial_management.services import receipt_to_out
from Models import AgentRun, Chat, ChatMessage, Comment, Document, Draft, User
from Models.chat import ChatRole
from routs.documents import _get_accessible_document_ids
from assistant.schemas import DraftOut
from schemas.chat import (
    ChatHistoryResponse,
    ChatListItem,
    ChatListResponse,
    ChatMessageItem,
    ChatRequest,
    ChatResponse,
    ChatUpdateNameRequest,
    RetrieveInformation,
    RetrievedItem,
)

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
    citations: list[Any] | None = None,
    retrieved_chunks: list[dict] | None = None,
    draft_id: int | None = None,
) -> ChatMessage:
    message = ChatMessage(
        chat_id=chat_id,
        role=role,
        content=content,
        citations=jsonable_encoder(citations) if citations is not None else None,
        retrieved_chunks=(
            jsonable_encoder(retrieved_chunks)
            if retrieved_chunks is not None
            else None
        ),
        draft_id=draft_id,
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


def _jsonable_model(model_obj) -> dict:
    return model_obj.model_dump(mode="json")


APP_RESOURCE_TYPES = [
    "document",
    "tag",
    "model",
    "comment",
    "receipt",
    "credit_card",
    "customer",
    "warehouse_item",
    "connection",
    "unknown",
]


def _resource_type_for_source(source_type: str | None) -> str:
    mapping = {
        "document_chunk": "document",
        "comment": "comment",
        "financial_receipt": "receipt",
        "model_receipt_note": "connection",
        "tag_receipt_note": "connection",
        "financial_receipt_comment_note": "connection",
        "receipt_note": "connection",
    }
    return mapping.get(source_type or "", "unknown")


def _empty_resource_groups() -> dict[str, list[RetrievedItem]]:
    return {resource_type: [] for resource_type in APP_RESOURCE_TYPES}


def _safe_title(*parts) -> str:
    values = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return " ".join(values)


def _resource_ref(resource_type: str, resource_id, title: str | None = None) -> dict:
    return {
        "resource_type": resource_type,
        "id": resource_id,
        "title": title or f"{resource_type.replace('_', ' ').title()} #{resource_id}",
    }


def _build_document_chunk_item(chunk, doc_name_map: dict[int, str]) -> dict:
    doc_name = doc_name_map.get(chunk.doc_id, "")
    data = {
        "id": chunk.doc_id,
        "filename": doc_name,
        "chunk": {
            "id": chunk.id,
            "page_num": chunk.page_num,
            "chunk_page": chunk.page_num + 1,
            "chunk_type": chunk.chunk_type,
            "content": chunk.content,
            "start_pos": chunk.start_pos,
            "end_pos": chunk.end_pos,
            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
        },
    }
    return {
        "resource_type": "document",
        "source_type": "document_chunk",
        "citation_key": f"chunk:{chunk.id}",
        "title": doc_name,
        "data": data,
    }


def _build_comment_item(comment) -> dict:
    files = []
    for file_rec in list(getattr(comment, "files", []) or []):
        files.append(
            {
                "id": file_rec.id,
                "file_name": file_rec.file_name,
                "media_address": file_rec.media_address,
                "asset_id": getattr(file_rec, "asset_id", None),
            }
        )

    data = {
        "id": comment.id,
        "user_id": comment.user_id,
        "title": comment.title,
        "doc_id": getattr(comment, "doc_id", None),
        "chunk_id": getattr(comment, "chunk_id", None),
        "type": comment.type.value if hasattr(comment.type, "value") else str(comment.type),
        "content": comment.content,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "files": files,
    }
    return {
        "resource_type": "comment",
        "source_type": "comment",
        "citation_key": f"comment:{comment.id}",
        "title": comment.title,
        "data": data,
    }


def _load_receipt_outputs(
    db: Session,
    *,
    receipt_ids: list[int],
    company_id: int,
) -> dict[int, dict]:
    if not receipt_ids:
        return {}

    receipts = (
        db.query(FinancialReceipt)
        .options(
            joinedload(FinancialReceipt.credit_card),
            joinedload(FinancialReceipt.customer),
            joinedload(FinancialReceipt.files),
        )
        .filter(
            FinancialReceipt.id.in_(receipt_ids),
            FinancialReceipt.company_id == company_id,
        )
        .all()
    )

    return {receipt.id: _jsonable_model(receipt_to_out(receipt)) for receipt in receipts}


def _build_receipt_item(receipt: dict, receipt_out_map: dict[int, dict]) -> dict:
    receipt_id = receipt.get("receipt_id")
    data = receipt_out_map.get(receipt_id)

    if data is None:
        data = {
            "id": receipt_id,
            "company_id": receipt.get("company_id"),
            "owner_id": receipt.get("owner_id"),
            "description": receipt.get("description"),
            "tracking_number": receipt.get("tracking_number"),
            "amount": str(receipt.get("amount")) if receipt.get("amount") is not None else None,
            "direction": str(receipt.get("direction")) if receipt.get("direction") is not None else None,
            "counterparty_name": receipt.get("counterparty_name"),
            "receipt_date": str(receipt.get("receipt_date")) if receipt.get("receipt_date") is not None else None,
            "credit_card": {
                "id": receipt.get("credit_card_id"),
                "title": receipt.get("card_title"),
                "card_number": receipt.get("card_number"),
            },
            "customer_id": receipt.get("customer_id"),
            "customer": None,
            "embedding_status": "available",
            "created_at": str(receipt.get("createdAt")) if receipt.get("createdAt") is not None else None,
            "updated_at": None,
            "files": [],
        }

    return {
        "resource_type": "receipt",
        "source_type": "financial_receipt",
        "citation_key": f"receipt:{receipt_id}",
        "title": f"Receipt #{receipt_id}",
        "data": data,
    }


def _jsonable_note(note: dict) -> dict:
    data = {}
    for key, value in note.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
        elif key in {"amount"} and value is not None:
            data[key] = str(value)
        elif hasattr(value, "value"):
            data[key] = value.value
        else:
            data[key] = value
    return data


def _connection_meta(data: dict) -> dict:
    keys = [
        "receipt_description",
        "amount",
        "direction",
        "counterparty_name",
        "receipt_date",
        "tracking_number",
        "similarity",
    ]
    return {key: data.get(key) for key in keys if data.get(key) is not None}


def _build_receipt_note_item(note: dict) -> dict:
    source_type = note.get("source_type") or "receipt_note"
    receipt_id = note.get("receipt_id")
    data = _jsonable_note(note)

    if source_type == "model_receipt_note":
        model_id = data.get("model_id")
        model_title = _safe_title(data.get("model_manufacturer"), data.get("model_name")) or f"Model #{model_id}"
        citation_key = f"model-receipt-note:{model_id}:{receipt_id}"
        connection_data = {
            "connection_type": "model_receipt",
            "from": _resource_ref("model", model_id, model_title),
            "to": _resource_ref("receipt", receipt_id, f"Receipt #{receipt_id}"),
            "note": data.get("note"),
            "created_at": data.get("created_at"),
            "meta": _connection_meta(data),
        }
        title = "Model Receipt Connection"

    elif source_type == "tag_receipt_note":
        tag_id = data.get("tag_id")
        tag_title = data.get("tag_name") or data.get("tag_title") or data.get("name") or f"Tag #{tag_id}"
        citation_key = f"tag-receipt-note:{tag_id}:{receipt_id}"
        connection_data = {
            "connection_type": "tag_receipt",
            "from": _resource_ref("tag", tag_id, tag_title),
            "to": _resource_ref("receipt", receipt_id, f"Receipt #{receipt_id}"),
            "note": data.get("note"),
            "created_at": data.get("created_at"),
            "meta": _connection_meta(data),
        }
        title = "Tag Receipt Connection"

    elif source_type == "financial_receipt_comment_note":
        comment_id = data.get("comment_id")
        comment_title = data.get("comment_title") or f"Comment #{comment_id}"
        citation_key = f"receipt-comment-note:{receipt_id}:{comment_id}"
        connection_data = {
            "connection_type": "receipt_comment",
            "from": _resource_ref("receipt", receipt_id, f"Receipt #{receipt_id}"),
            "to": _resource_ref("comment", comment_id, comment_title),
            "note": data.get("note"),
            "created_at": data.get("created_at"),
            "meta": _connection_meta(data),
        }
        title = "Receipt Comment Connection"

    else:
        citation_key = f"receipt-note:{receipt_id}"
        connection_data = {
            "connection_type": "receipt_note",
            "from": _resource_ref("receipt", receipt_id, f"Receipt #{receipt_id}"),
            "to": None,
            "note": data.get("note"),
            "created_at": data.get("created_at"),
            "meta": _connection_meta(data),
        }
        title = "Receipt Note Connection"

    return {
        "resource_type": "connection",
        "source_type": source_type,
        "citation_key": citation_key,
        "title": title,
        "data": connection_data,
    }


def build_retrieved_items(
    db: Session,
    *,
    chunks: list,
    comments: list,
    receipts: list,
    receipt_notes: list,
    company_id: int,
) -> list[dict]:
    items: list[dict] = []

    doc_ids = {chunk.doc_id for chunk in chunks}
    docs = (
        db.query(Document.id, Document.filename)
        .filter(Document.id.in_(doc_ids))
        .all()
        if doc_ids
        else []
    )
    doc_name_map = {doc.id: doc.filename for doc in docs}

    for chunk in chunks:
        items.append(_build_document_chunk_item(chunk, doc_name_map))

    for comment in comments:
        items.append(_build_comment_item(comment))

    receipt_ids = [receipt.get("receipt_id") for receipt in receipts if receipt.get("receipt_id") is not None]
    receipt_ids += [note.get("receipt_id") for note in receipt_notes if note.get("receipt_id") is not None]
    receipt_out_map = _load_receipt_outputs(
        db,
        receipt_ids=list(dict.fromkeys(receipt_ids)),
        company_id=company_id,
    )

    for receipt in receipts:
        items.append(_build_receipt_item(receipt, receipt_out_map))

    for note in receipt_notes:
        items.append(_build_receipt_note_item(note))

    return items


def build_retrieve_information(retrieved_items: list[dict]) -> RetrieveInformation:
    items = [RetrievedItem.model_validate(_normalize_retrieved_item(item)) for item in retrieved_items]
    by_type = _empty_resource_groups()

    for item in items:
        by_type.setdefault(item.resource_type, []).append(item)

    return RetrieveInformation(items=items, by_type=by_type)


def build_chat_response(
    *,
    answer: str,
    citations: list[Any],
    retrieved_items: list[dict],
    chat_id: int,
) -> ChatResponse:
    retrieve_information = build_retrieve_information(retrieved_items)
    return ChatResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=retrieve_information.items,
        retrieve_information=retrieve_information,
        chat_id=chat_id,
    )


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
        user_id=current_user.id,
        receipt_ids=request.receipt_ids,
        scope="both",
    )

    result = await graph.ainvoke(state)

    retrieved_items = build_retrieved_items(
        db,
        chunks=result.get("chunks", []),
        comments=result.get("comments", []),
        receipts=result.get("receipts", []),
        receipt_notes=result.get("receipt_notes", []),
        company_id=current_user.company_id,
    )

    answer = result.get("answer") or ""
    citation_keys = [item.get("citation_key") for item in retrieved_items if item.get("citation_key")]

    if not request.preview:
        add_message(
            db,
            chat_id=chat_obj.id,
            role=ChatRole.assistant,
            content=answer,
            citations=citation_keys,
            retrieved_chunks=retrieved_items,
        )

    return build_chat_response(
        answer=answer,
        citations=citation_keys,
        retrieved_items=retrieved_items,
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
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
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
        .offset(offset)
        .limit(limit)
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


def _normalize_retrieved_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {
            "resource_type": "unknown",
            "source_type": "unknown",
            "citation_key": None,
            "title": "",
            "data": {},
        }

    source_type = item.get("source_type") or "unknown"

    if "data" in item:
        normalized = dict(item)
        normalized.setdefault("resource_type", _resource_type_for_source(source_type))
        normalized.setdefault("source_type", source_type)

        if normalized["resource_type"] == "connection" and source_type in {
            "model_receipt_note",
            "tag_receipt_note",
            "financial_receipt_comment_note",
            "receipt_note",
        }:
            data = normalized.get("data") or {}
            if not isinstance(data, dict) or "connection_type" not in data:
                return _build_receipt_note_item(data if isinstance(data, dict) else item)

        return normalized

    return {
        "resource_type": _resource_type_for_source(source_type),
        "source_type": source_type,
        "citation_key": item.get("citation_key"),
        "title": item.get("title") or "",
        "data": item,
    }


def _parse_retrieved_items(raw) -> list[RetrievedItem]:
    if not raw:
        return []

    parsed: list[RetrievedItem] = []

    for item in raw:
        if isinstance(item, dict):
            parsed.append(RetrievedItem.model_validate(_normalize_retrieved_item(item)))

    return parsed


@router.get("/{chat_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    chat_id: int,
    include_drafts: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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

    messages_query = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_obj.id)
        .order_by(desc(ChatMessage.id))
    )

    messages_query = messages_query.offset(offset).limit(limit)

    messages = messages_query.all()
    draft_items: list[dict[str, Any]] = []
    drafts_by_id: dict[int, dict[str, Any]] = {}

    if include_drafts:
        drafts = (
            db.query(Draft)
            .filter(
                Draft.chat_id == chat_obj.id,
                Draft.company_id == current_user.company_id,
                Draft.created_by_user_id == current_user.id,
            )
            .order_by(desc(Draft.id))
            .all()
        )
        draft_items = [
            DraftOut.model_validate(draft).model_dump(mode="json")
            for draft in drafts
        ]
        drafts_by_id = {draft["id"]: draft for draft in draft_items}

    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.chat_id == chat_obj.id,
            AgentRun.company_id == current_user.company_id,
            AgentRun.created_by_user_id == current_user.id,
        )
        .order_by(desc(AgentRun.id))
        .all()
    )
    run_details_by_message_id: dict[int, dict[str, Any]] = {}
    partial_draft_items: list[dict[str, Any]] = []

    for run in runs:
        state = run.state if isinstance(run.state, dict) else {}
        partial_draft = state.get("partial_draft")
        if not isinstance(partial_draft, dict):
            partial_draft = None
        elif include_drafts:
            partial_draft_items.append(partial_draft)

        output_message_id = getattr(run, "output_message_id", None)
        if output_message_id is not None and output_message_id not in run_details_by_message_id:
            summary = state.get("summary")
            run_details_by_message_id[output_message_id] = {
                "agent_run_id": run.id,
                "summary": summary if isinstance(summary, dict) else None,
                "intent": getattr(run, "intent", None) or state.get("intent"),
                "partial_draft": partial_draft if include_drafts else None,
            }

    message_items = []

    for message in messages:
        run_details = run_details_by_message_id.get(message.id, {})
        retrieved_items = _parse_retrieved_items(message.retrieved_chunks)
        retrieve_information = RetrieveInformation(
            items=retrieved_items,
            by_type=_empty_resource_groups(),
        )

        for item in retrieved_items:
            retrieve_information.by_type.setdefault(item.resource_type, []).append(item)

        message_items.append(
            ChatMessageItem(
                id=message.id,
                role=message.role.value if hasattr(message.role, "value") else str(message.role),
                content=message.content,
                citations=message.citations or [],
                retrieved_chunks=retrieved_items,
                retrieve_information=retrieve_information,
                agent_run_id=run_details.get("agent_run_id"),
                summary=run_details.get("summary"),
                intent=run_details.get("intent"),
                draft_id=getattr(message, "draft_id", None),
                draft=drafts_by_id.get(getattr(message, "draft_id", None)),
                partial_draft=run_details.get("partial_draft"),
                created_at=message.created_at,
            )
        )

    return ChatHistoryResponse(
        chat_id=chat_obj.id,
        name=chat_obj.name,
        messages=message_items,
        drafts=draft_items,
        partial_drafts=partial_draft_items,
    )
