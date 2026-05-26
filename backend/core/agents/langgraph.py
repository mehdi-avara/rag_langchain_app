from typing import Any, Dict, List, TypedDict

from langchain.prompts import ChatPromptTemplate
from langgraph.graph import Graph, StateGraph
from sqlalchemy import text
from sqlalchemy.orm import Session

from Models import Chunk, Comment
from components.embedding import JinaAPIEmbeddings
from components.llm import llm_client, raise_llm_exception
from core.exceptions import AppException
from financial_management.search.repository import search_financial_receipt_hits_semantic
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB
from retrieval.vector.postgres_store import PostgresVectorStore
from settings import get_settings

settings = get_settings()


class GraphState(TypedDict):
    question: str
    route: str
    chunks: List[Chunk]
    comments: List[Comment]
    receipts: List[Dict[str, Any]]
    receipt_notes: List[Dict[str, Any]]
    answer: str
    citations: List[int]
    mode: str
    db: Session
    doc_ids: List[int] | None
    comment_ids: List[int] | None
    receipt_ids: List[int] | None
    company_id: int | None
    user_id: int | None
    scope: str | None


def _query_embedding_string(query: str) -> str | None:
    try:
        vector = JinaAPIEmbeddings(fail_soft=True).embed_query(query)
    except Exception:
        return None

    if not vector:
        return None

    return "[" + ",".join(map(str, vector)) + "]"


def _search_receipts(
    db: Session,
    *,
    question: str,
    company_id: int | None,
    receipt_ids: List[int] | None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if company_id is None:
        return []

    try:
        return search_financial_receipt_hits_semantic(
            db=db,
            query_text=question,
            company_id=company_id,
            receipt_ids=receipt_ids,
            limit=limit,
        )
    except Exception:
        return []


def _search_model_receipt_notes(
    db: Session,
    *,
    query_vec: str,
    company_id: int,
    receipt_ids: List[int] | None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    filters = [
        "m.company_id = :company_id",
        "r.company_id = :company_id",
        "l.note_embedding IS NOT NULL",
        "l.note IS NOT NULL",
        "NULLIF(BTRIM(l.note), '') IS NOT NULL",
    ]
    params: Dict[str, Any] = {
        "company_id": company_id,
        "query_vec": query_vec,
        "limit": limit,
    }

    if receipt_ids is not None:
        if not receipt_ids:
            return []
        placeholders = ", ".join(f":receipt_id_{i}" for i in range(len(receipt_ids)))
        filters.append(f"l.receipt_id IN ({placeholders})")
        for i, receipt_id in enumerate(receipt_ids):
            params[f"receipt_id_{i}"] = receipt_id

    sql = text(
        f"""
        SELECT
            'model_receipt_note' AS source_type,
            l.model_id AS model_id,
            l.receipt_id AS receipt_id,
            l.note AS note,
            l.created_at AS created_at,
            m.manufacturer AS model_manufacturer,
            m.model AS model_name,
            r.description AS receipt_description,
            r.amount AS amount,
            r.direction AS direction,
            r.counterparty_name AS counterparty_name,
            r.receipt_date AS receipt_date,
            r.tracking_number AS tracking_number,
            (1 - (l.note_embedding <=> (:query_vec)::vector)) AS similarity
        FROM model_receipt_links l
        JOIN managed_models m ON m.id = l.model_id
        JOIN financial_receipts r ON r.id = l.receipt_id
        WHERE {" AND ".join(filters)}
        ORDER BY similarity DESC, l.created_at DESC
        LIMIT :limit
        """
    )

    return [dict(row._mapping) for row in db.execute(sql, params).fetchall()]


def _search_tag_receipt_notes(
    db: Session,
    *,
    query_vec: str,
    company_id: int,
    receipt_ids: List[int] | None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    filters = [
        "st.company_id = :company_id",
        "r.company_id = :company_id",
        "l.note_embedding IS NOT NULL",
        "l.note IS NOT NULL",
        "NULLIF(BTRIM(l.note), '') IS NOT NULL",
    ]
    params: Dict[str, Any] = {
        "company_id": company_id,
        "query_vec": query_vec,
        "limit": limit,
    }

    if receipt_ids is not None:
        if not receipt_ids:
            return []
        placeholders = ", ".join(f":receipt_id_{i}" for i in range(len(receipt_ids)))
        filters.append(f"l.receipt_id IN ({placeholders})")
        for i, receipt_id in enumerate(receipt_ids):
            params[f"receipt_id_{i}"] = receipt_id

    sql = text(
        f"""
        SELECT
            'tag_receipt_note' AS source_type,
            l.tag_id AS tag_id,
            l.receipt_id AS receipt_id,
            l.note AS note,
            l.created_at AS created_at,
            r.description AS receipt_description,
            r.amount AS amount,
            r.direction AS direction,
            r.counterparty_name AS counterparty_name,
            r.receipt_date AS receipt_date,
            r.tracking_number AS tracking_number,
            (1 - (l.note_embedding <=> (:query_vec)::vector)) AS similarity
        FROM tag_receipt_links l
        JOIN system_tags st ON st.id = l.tag_id
        JOIN financial_receipts r ON r.id = l.receipt_id
        WHERE {" AND ".join(filters)}
        ORDER BY similarity DESC, l.created_at DESC
        LIMIT :limit
        """
    )

    return [dict(row._mapping) for row in db.execute(sql, params).fetchall()]


def _search_financial_receipt_comment_notes(
    db: Session,
    *,
    query_vec: str,
    company_id: int,
    user_id: int | None,
    receipt_ids: List[int] | None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if user_id is None:
        return []

    filters = [
        "r.company_id = :company_id",
        "l.linked_by_user_id = :user_id",
        "l.note_embedding IS NOT NULL",
        "l.note IS NOT NULL",
        "NULLIF(BTRIM(l.note), '') IS NOT NULL",
    ]
    params: Dict[str, Any] = {
        "company_id": company_id,
        "user_id": user_id,
        "query_vec": query_vec,
        "limit": limit,
    }

    if receipt_ids is not None:
        if not receipt_ids:
            return []
        placeholders = ", ".join(f":receipt_id_{i}" for i in range(len(receipt_ids)))
        filters.append(f"l.receipt_id IN ({placeholders})")
        for i, receipt_id in enumerate(receipt_ids):
            params[f"receipt_id_{i}"] = receipt_id

    sql = text(
        f"""
        SELECT
            'financial_receipt_comment_note' AS source_type,
            l.receipt_id AS receipt_id,
            l.comment_id AS comment_id,
            l.note AS note,
            l.created_at AS created_at,
            c.title AS comment_title,
            c.content AS comment_content,
            r.description AS receipt_description,
            r.amount AS amount,
            r.direction AS direction,
            r.counterparty_name AS counterparty_name,
            r.receipt_date AS receipt_date,
            r.tracking_number AS tracking_number,
            (1 - (l.note_embedding <=> (:query_vec)::vector)) AS similarity
        FROM financial_receipt_comment_links l
        JOIN financial_receipts r ON r.id = l.receipt_id
        JOIN comments c ON c.id = l.comment_id
        WHERE {" AND ".join(filters)}
        ORDER BY similarity DESC, l.created_at DESC
        LIMIT :limit
        """
    )

    return [dict(row._mapping) for row in db.execute(sql, params).fetchall()]


def _search_receipt_notes(
    db: Session,
    *,
    question: str,
    company_id: int | None,
    user_id: int | None,
    receipt_ids: List[int] | None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if company_id is None:
        return []

    query_vec = _query_embedding_string(question)
    if not query_vec:
        return []

    results: List[Dict[str, Any]] = []
    results.extend(
        _search_model_receipt_notes(
            db,
            query_vec=query_vec,
            company_id=company_id,
            receipt_ids=receipt_ids,
            limit=limit,
        )
    )
    results.extend(
        _search_tag_receipt_notes(
            db,
            query_vec=query_vec,
            company_id=company_id,
            receipt_ids=receipt_ids,
            limit=limit,
        )
    )
    results.extend(
        _search_financial_receipt_comment_notes(
            db,
            query_vec=query_vec,
            company_id=company_id,
            user_id=user_id,
            receipt_ids=receipt_ids,
            limit=limit,
        )
    )

    results.sort(key=lambda item: item.get("similarity") or 0, reverse=True)
    return results[:limit]


async def retrieve_docs(state: GraphState) -> GraphState:
    question = f"search_query: {state.get('question')}"
    mode = state.get("mode", "hybrid")
    db = state.get("db")
    scope = state.get("scope", "both")

    keyword_retriever = FullTextRetrieverFromDB(db)
    vector_store = PostgresVectorStore(db)
    vector_retriever = vector_store.as_retriever(
        search_kwargs={"k": 6},
        doc_ids=state.get("doc_ids", None),
        comment_ids=state.get("comment_ids", None),
        company_id=state.get("company_id", None),
    )

    comments = []
    chunks = []
    receipts = []
    receipt_notes = []

    if mode == "keyword":
        chunks = await keyword_retriever.ainvoke(
            question,
            doc_ids=state.get("doc_ids", None),
            company_id=state.get("company_id", None),
        )
    elif mode == "vector":
        retrieved_content = vector_retriever.invoke(question)
        chunks = retrieved_content["chunks"]
        comments = retrieved_content["comments"]
    elif mode == "hybrid":
        retrieved_content = vector_retriever.invoke(question)
        chunks = retrieved_content["chunks"]
        comments = retrieved_content["comments"]
        holder = await keyword_retriever.ainvoke(
            question,
            doc_ids=state.get("doc_ids", None),
            company_id=state.get("company_id", None),
        )
        chunks += holder

    if scope in {"both", "financial", "receipts"}:
        receipts = _search_receipts(
            db,
            question=question,
            company_id=state.get("company_id", None),
            receipt_ids=state.get("receipt_ids", None),
            limit=6,
        )
        receipt_notes = _search_receipt_notes(
            db,
            question=question,
            company_id=state.get("company_id", None),
            user_id=state.get("user_id", None),
            receipt_ids=state.get("receipt_ids", None),
            limit=6,
        )

    comment_ids = state.get("comment_ids")
    if comment_ids is not None:
        allowed = set(comment_ids)
        comments = [comment for comment in comments if comment.id in allowed]

    if scope == "comments":
        chunks = []
        receipts = []
        receipt_notes = []
    elif scope == "docs":
        comments = []
        receipts = []
        receipt_notes = []
    elif scope in {"financial", "receipts"}:
        chunks = []
        comments = []

    return {
        **state,
        "chunks": chunks,
        "comments": comments,
        "receipts": receipts,
        "receipt_notes": receipt_notes,
    }


def _receipt_note_citation(note: Dict[str, Any]) -> str:
    source_type = note.get("source_type")
    if source_type == "model_receipt_note":
        return f"[model-receipt-note:{note.get('model_id')}:{note.get('receipt_id')}]"
    if source_type == "tag_receipt_note":
        return f"[tag-receipt-note:{note.get('tag_id')}:{note.get('receipt_id')}]"
    if source_type == "financial_receipt_comment_note":
        return f"[receipt-comment-note:{note.get('receipt_id')}:{note.get('comment_id')}]"
    return "[receipt-note:unknown]"


def _build_context(chunks: List[Chunk], comments: List[Comment], receipts: List[Dict[str, Any]], receipt_notes: List[Dict[str, Any]]) -> str:
    parts = []

    for chunk in chunks:
        parts.append(
            f"[chunk:{chunk.id}]\n"
            f"document_id={chunk.doc_id}\n"
            f"page={chunk.page_num}\n"
            f"content={chunk.content}"
        )

    for comment in comments:
        parts.append(
            f"[comment:{comment.id}]\n"
            f"title={comment.title}\n"
            f"type={comment.type}\n"
            f"content={comment.content}"
        )

    for receipt in receipts:
        tracking_number = receipt.get("tracking_number") or "-"
        parts.append(
            f"[receipt:{receipt['receipt_id']}]\n"
            f"date={receipt.get('receipt_date')}\n"
            f"direction={receipt.get('direction')}\n"
            f"amount={receipt.get('amount')}\n"
            f"counterparty={receipt.get('counterparty_name')}\n"
            f"tracking={tracking_number}\n"
            f"card={receipt.get('card_title')}({receipt.get('card_number')})\n"
            f"description={receipt.get('description')}"
        )

    for note in receipt_notes:
        citation = _receipt_note_citation(note)
        parts.append(
            f"{citation}\n"
            f"source_type={note.get('source_type')}\n"
            f"receipt_id={note.get('receipt_id')}\n"
            f"amount={note.get('amount')}\n"
            f"direction={note.get('direction')}\n"
            f"counterparty={note.get('counterparty_name')}\n"
            f"tracking={note.get('tracking_number') or '-'}\n"
            f"receipt_description={note.get('receipt_description')}\n"
            f"note={note.get('note')}"
        )

    return "\n\n".join(parts) if parts else "(no context)"


async def generate_answer(state: GraphState) -> GraphState:
    question = state["question"]
    chunks = state.get("chunks", [])
    comments = state.get("comments", [])
    receipts = state.get("receipts", [])
    receipt_notes = state.get("receipt_notes", [])

    template = """Use ONLY the provided context to answer the question.
Cite sources exactly using [chunk:id], [comment:id], [receipt:id], [model-receipt-note:model_id:receipt_id], [tag-receipt-note:tag_id:receipt_id], or [receipt-comment-note:receipt_id:comment_id].
If the context is insufficient, say so clearly.

Context:
{context}

Question: {question}

Answer:"""

    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm_client.langchain_llm

    context = _build_context(chunks, comments, receipts, receipt_notes)

    try:
        result = await chain.ainvoke({
            "context": context,
            "question": question,
        })
    except AppException:
        raise
    except Exception as exc:
        raise_llm_exception(exc, "chat_generate_answer")

    return {
        **state,
        "answer": result.content.strip(),
        "context": context,
        "citations": [],
    }


def end_node(state: GraphState) -> GraphState:
    return state


def build_answer_graph() -> Graph:
    workflow = StateGraph(GraphState)

    workflow.add_node("retrieve", retrieve_docs)
    workflow.add_node("generate", generate_answer)
    workflow.add_node("end", end_node)

    def should_generate(state: GraphState) -> str:
        return "generate" if state.get("route", "full") == "full" else "end"

    workflow.add_conditional_edges(
        "retrieve",
        should_generate,
        {
            "generate": "generate",
            "end": "end",
        },
    )

    workflow.add_edge("generate", "end")
    workflow.set_entry_point("retrieve")
    workflow.set_finish_point("end")

    return workflow.compile()
