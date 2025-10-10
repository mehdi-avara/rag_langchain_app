from typing import List, Dict, Any
from fastapi import HTTPException
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from db.models import Document as DBDocument
from retrieval.vector.chroma_store import ChromaStore
from settings import get_settings
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB

from langchain.tools import tool
from components.llm import llm_client

settings = get_settings()

@tool
async def retrieve_docs_tool(question: str, route: str = "hybrid", mode: str = "full", db: Session = None) -> List[Document]:
    """
    Retrieve relevant documents from the database using a specified retrieval strategy.

    This tool supports three retrieval modes:
    - 'keyword': Uses full-text keyword matching to find relevant documents.
    - 'vector': Uses semantic similarity search via a vector store (e.g., Chroma).
    - 'hybrid': Combines both vector and keyword search results.

    Parameters:
    - question (str): The natural language query to search for.
    - route (str): The retrieval method to use ('keyword', 'vector', or 'hybrid'). Defaults to 'hybrid'.
    - mode (str): The retrieval depth mode. 'full' fetches more documents than 'preview'. Defaults to 'full'.
    - db (Session): SQLAlchemy session connected to the document database.

    Returns:
    - List[Document]: A list of retrieved documents relevant to the input question.
    """
    if db is None:
        raise ValueError("Database session must be provided for retrieval.")
    keyword_retriever = FullTextRetrieverFromDB(db)
    vector_retriever = ChromaStore().as_retriever(
        search_kwargs={"k": 6 if mode == "full" else 3}
    )
    
    if route == "keyword":
        docs = await keyword_retriever.ainvoke(question)
    elif route == "vector":
        docs = await vector_retriever.ainvoke(question)
    elif route == "hybrid":
        docs = await vector_retriever.ainvoke(question)
        holder = await keyword_retriever.ainvoke(question)
        docs += holder
    else:
        docs = []
    return docs

@tool
async def fetch_adjacent_chunks_tool(docs: List[Document]) -> List[Document]:
    """Dummy tool placeholder for fetching adjacent chunks or additional context."""
    # Implement logic if needed; for now, just return input docs
    return docs

template = (
    "Use ONLY the provided context to answer the question. "
    "Cite sources using [chunk:id].\n\n"
    "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
)

async def run_llm(context: str, question: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that answers strictly from the provided context."
        },
        {
            "role": "user",
            "content": template.format(context=context, question=question)
        }
    ]
    response = await llm_client.async_openai_client.chat.completions.create(
        model=llm_client.settings.llm_model,
        temperature=llm_client.settings.llm_temperature,
        max_tokens=llm_client.settings.llm_max_tokens,
        messages=messages
    )
    return response.choices[0].message.content.strip()

async def answer_question_with_agent(question: str, route: str, mode: str, db: Session) -> Dict[str, Any]:
    """Run the agent to answer the question using the specified route and mode."""
    # Retrieve documents first
    docs = await retrieve_docs_tool(question=question, route=route, mode=mode, db=db)
    # Optionally fetch adjacent chunks or enrich docs
    enriched_docs = await fetch_adjacent_chunks_tool(docs=docs)
    # Prepare context and run async OpenAI
    context = "\n\n".join(doc.page_content for doc in enriched_docs)
    answer_text = await run_llm(context=context, question=question)
    # Extract citations
    citations = []
    for doc in enriched_docs:
        if "chunk_id" in doc.metadata:
            citations.append(doc.metadata["chunk_id"])
    return {
        "answer": answer_text,
        "citations": citations
    }