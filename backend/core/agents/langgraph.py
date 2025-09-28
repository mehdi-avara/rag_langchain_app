
from typing import Dict, List, TypedDict, Tuple
from fastapi import HTTPException
from langgraph.graph import Graph, StateGraph
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from openai import base_url
from sqlalchemy.orm import Session

from db.models import Chunk
from retrieval.vector.postgres_store import PostgresVectorStore
from settings import get_settings
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB


from langchain_core.runnables import Runnable
from typing import Any

settings = get_settings()

class GraphState(TypedDict):
    question: str
    route: str
    chunks: List[Chunk]
    answer: str
    citations: List[int]
    mode: str  # Can be "preview" or "full"
    db: Session  # SQLAlchemy session for database access


async def retrieve_docs(state: GraphState) -> GraphState:
    """Retrieve relevant documents based on route."""
    question = f"search_query: {state["question"]}"
    mode = state.get("mode", "hybrid")  # Default to full mode if not specified
    db = state.get("db")  # Assume db session is passed in state
    keyword_retriever = FullTextRetrieverFromDB(db)
    vector_store = PostgresVectorStore(db)
    vector_retriever = vector_store.as_retriever(
        search_kwargs={"k": 6 if mode == "vector" else 3}  # Use fewer results for preview
    )
    
    # Manual routing logic
    if mode == "keyword":
        chunks = await keyword_retriever.ainvoke(question)
    elif mode == "vector":
        chunks = vector_retriever.invoke(question)
    elif mode == "hybrid":
        chunks = vector_retriever.invoke(question)
        holder = await keyword_retriever.ainvoke(question)
        chunks += holder
    else:
        chunks = []
    
    return {**state, "chunks": chunks}

async def generate_answer(state: GraphState) -> GraphState:
    """Generate answer using retrieved documents."""
    question = state["question"]
    chunks = state["chunks"]
    
    # Create prompt template
    template = """Use ONLY the provided context to answer the question. Cite sources using [chunk:id].

Context:
{context}

Question: {question}

Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    
    # Initialize LLM
    llm = ChatOpenAI(
        base_url=settings.openai_base_url,
        model="gemma_3_vision",
        temperature=0.1,
        openai_api_key=settings.openai_api_key
    )
    # Generate answer
    chain = prompt | llm
    context = "\n\n".join(f"context Id:{chunk.id}\ncontext content:{chunk.content}" for chunk in chunks)
    result = await chain.ainvoke({
        "context": context,
        "question": question
    })
    
    # Extract citations
    citations = []
    for chunk in chunks:
        if "chunk_id" in chunk.metadata:
            citations.append(chunk.metadata["chunk_id"])
    
    return {
        **state,
        "answer": result.content.strip(),
        "context": context,
        "citations": citations
    }


def end_node(state: GraphState) -> GraphState:
    
    return state  # No-op, just returns the state

def build_answer_graph() -> Graph:
    """Build the answer generation graph."""
    # Create graph
    workflow = StateGraph(GraphState)
    
    # Add nodes
    workflow.add_node("retrieve", retrieve_docs)
    workflow.add_node("generate", generate_answer)
    workflow.add_node("end", end_node)
    # Add edges with conditional routing
    def should_generate(state: GraphState) -> str:
        return "generate" if state.get("route", "full") == "full" else "end"
    
    workflow.add_conditional_edges(
        "retrieve",
        should_generate,
        {
            "generate": "generate",
            "end": "end"
        }
    )
    
    # Set entry point
    workflow.set_entry_point("retrieve")
    
    # Compile
    return workflow.compile()
