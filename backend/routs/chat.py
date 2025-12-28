from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from schemas.chat import ChatRequest, ChatResponse, ChatUpdateNameRequest, Retrieved_data
from db.init_db import get_db
from deps import get_current_user
from Models import Chat, ChatMessage, User, Document, DocumentStatusType, SystemTag
from core.agents import build_answer_graph , GraphState, call_llm_to_rewrite
from Models.chat import ChatRole
from settings import get_settings

router = APIRouter()

# Chat route /chat itself
@router.post("")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ChatResponse:
    chat_id = request.chat_id
    
    if chat_id:
        chat = (
            db.query(Chat)
            .filter(
                Chat.id == chat_id,
                Chat.user_id == current_user.id
            )
            .first()
        )
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        chat = Chat(
            name="New Chat",
            user_id=current_user.id,
        )
        db.add(chat)
        db.commit()
        db.refresh(chat)
    
    query = request.query
    
    user_message = ChatMessage(
        chat_id=chat.id,
        role=ChatRole.user,
        content=query,
    )

    db.add(user_message)
    db.commit()
    
    # Query rewriting if requested
    if request.rewrite_query:
        query = await call_llm_to_rewrite(query)
    route = "full"
    if request.preview == True:
        route = "search"
    answer_graph = build_answer_graph()
    
    state_graph = GraphState(
        question=query,
        route=route,  
        db=db,  # Pass the database session
        mode="vector",
        doc_ids=request.doc_ids
    )
    result = await answer_graph.ainvoke(state_graph)
    answer = result["answer"]
    
    
    retrieved_data: list[Retrieved_data] = []
    citations: list[int] = []

    chunks = result.get("chunks", []) or []
    comments = result.get("comments", []) or []

    # 1) Collect all doc_ids from chunks and comments where doc_id is not None
    doc_ids: set[int] = {chunk.doc_id for chunk in chunks}
    doc_ids |= {comment.doc_id for comment in comments if comment.doc_id is not None}

    # 2) Load all documents (id, filename, system_tag_id)
    if doc_ids:
        docs = (
            db.query(
                Document.id,
                Document.filename,
                Document.system_tag_id,
            )
            .filter(Document.id.in_(doc_ids))
            .all()
        )
    else:
        docs = []

    # Maps: doc_id -> filename / tag_id
    doc_name_map: dict[int, str] = {doc.id: doc.filename for doc in docs}
    doc_tag_map: dict[int, int] = {doc.id: doc.system_tag_id for doc in docs}

    # 3) Collect all tag_ids from docs and comments
    tag_ids: set[int] = {doc.system_tag_id for doc in docs}
    tag_ids |= {comment.system_tag_id for comment in comments}

    # 4) Load all tags
    if tag_ids:
        tags = (
            db.query(
                SystemTag.id,
                SystemTag.tag_name,
                SystemTag.description,
            )
            .filter(SystemTag.id.in_(tag_ids))
            .all()
        )
    else:
        tags = []

    # tag_id -> tag_name
    tag_name_map: dict[int, str] = {tag.id: tag.tag_name for tag in tags}

    # ------------------------
    # CHUNKS
    # ------------------------
    for chunk in chunks:
        # doc_id is NOT nullable on chunk, so this is safe:
        tag_id = doc_tag_map[chunk.doc_id]
        tag_name = tag_name_map[tag_id]

        retrieved_data.append(
            Retrieved_data(
                content=chunk.content,
                doc_id=chunk.doc_id,
                tag_id=tag_id,
                tag_name=tag_name,
                doc_name=doc_name_map[chunk.doc_id],
                title=doc_name_map[chunk.doc_id],  # using filename as title
                chunk_id=chunk.id,
                chunk_page=chunk.page_num + 1,     # 1-based index
                comment_id=None,
                comment_type=None,
            )
        )

        citations.append(chunk.id)

    # ------------------------
    # COMMENTS
    # ------------------------
    for comment in comments:
        # tag comes directly from comment
        tag_id = comment.system_tag_id
        tag_name = tag_name_map[tag_id]

        # doc_id can be None on comment → avoid KeyError
        if comment.doc_id is not None:
            doc_name = doc_name_map.get(comment.doc_id, "")
        else:
            doc_name = ""  # no associated doc; model requires non-null str

        retrieved_data.append(
            Retrieved_data(
                content=comment.content,
                doc_id=comment.doc_id,  # can be None
                tag_id=tag_id,
                tag_name=tag_name,
                doc_name=doc_name,
                title=comment.title,
                chunk_id=comment.chunk_id,
                chunk_page=None,
                comment_id=comment.id,
                comment_type=comment.type,
            )
        )

    assistant_message = ChatMessage(
        chat_id=chat.id,
        role=ChatRole.assistant,
        content=answer,
        citations=citations,
        retrieved_chunks=[c.model_dump() for c in retrieved_data],
    )
    
    db.add(assistant_message)
    db.commit()
    
    return {"answer": answer, "citations": citations, "retrieved_chunks": retrieved_data, "chat_id": chat.id}



@router.patch("/{chat_id}/name")
async def update_chat_name(
    chat_id: int,
    request: ChatUpdateNameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat.name = request.name
    db.commit()
    db.refresh(chat)

    return {"chat_id": chat.id, "name": chat.name}