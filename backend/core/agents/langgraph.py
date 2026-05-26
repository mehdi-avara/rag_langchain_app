from typing import Any, Dict, List, TypedDict

from langchain.prompts import ChatPromptTemplate
from langgraph.graph import Graph, StateGraph
from sqlalchemy.orm import Session

from Models import Chunk, Comment
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
    answer: str
    citations: List[int]
    mode: str
    db: Session
    doc_ids: List[int] | None
    comment_ids: List[int] | None
    receipt_ids: List[int] | None
    company_id: int | None
    scope: str | None


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

    comment_ids = state.get("comment_ids")
    if comment_ids is not None:
        allowed = set(comment_ids)
        comments = [comment for comment in comments if comment.id in allowed]

    if scope == "comments":
        chunks = []
        receipts = []
    elif scope == "docs":
        comments = []
        receipts = []
    elif scope in {"financial", "receipts"}:
        chunks = []
        comments = []

    return {
        **state,
        "chunks": chunks,
        "comments": comments,
        "receipts": receipts,
    }


def _build_context(chunks: List[Chunk], comments: List[Comment], receipts: List[Dict[str, Any]]) -> str:
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

    return "\n\n".join(parts) if parts else "(no context)"


async def generate_answer(state: GraphState) -> GraphState:
    question = state["question"]
    chunks = state.get("chunks", [])
    comments = state.get("comments", [])
    receipts = state.get("receipts", [])

    template = """Use ONLY the provided context to answer the question.
Cite sources exactly using [chunk:id], [comment:id], or [receipt:id].
If the context is insufficient, say so clearly.

Context:
{context}

Question: {question}

Answer:"""

    prompt = ChatPromptTemplate.from_template(template)
    llm = llm_client.langchain_llm
    chain = prompt | llm

    context = _build_context(chunks, comments, receipts)

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
