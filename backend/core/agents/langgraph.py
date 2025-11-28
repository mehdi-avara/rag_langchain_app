
from typing import Dict, List, TypedDict, Tuple
from fastapi import HTTPException
from langgraph.graph import Graph, StateGraph
from langchain.prompts import ChatPromptTemplate
from sqlalchemy.orm import Session
from langchain.chat_models import ChatOpenAI


from Models import Chunk, Comment
from retrieval.vector.postgres_store import PostgresVectorStore
from settings import get_settings
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB
from components.llm import llm_client


from langchain_core.runnables import Runnable
from typing import Any

settings = get_settings()

class GraphState(TypedDict):
    question: str
    route: str
    chunks: List[Chunk]
    comments: List[Comment]
    answer: str
    citations: List[int]
    mode: str  # Can be "preview" or "full"
    db: Session  # SQLAlchemy session for database access
    doc_ids: List[int] | None
    

async def retrieve_docs(state: GraphState) -> GraphState:
    """Retrieve relevant documents based on route."""
    question = f"search_query: {state.get('question')}"
    mode = state.get("mode", "hybrid")  # Default to full mode if not specified
    db = state.get("db")  # Assume db session is passed in state
    keyword_retriever = FullTextRetrieverFromDB(db)
    vector_store = PostgresVectorStore(db)
    vector_retriever = vector_store.as_retriever(
        search_kwargs={"k": 6},  # Use fewer results for preview
        doc_ids=state.get("doc_ids", None)
    )
    comments = []
    chunks = []
    # Manual routing logic
    if mode == "keyword":
        chunks = await keyword_retriever.ainvoke(question)
    elif mode == "vector":
        retrieved_content = vector_retriever.invoke(question)
        chunks = retrieved_content["chunks"]  
        comments = retrieved_content["comments"]
    elif mode == "hybrid":
        retrieved_content = vector_retriever.invoke(question)
        chunks = retrieved_content["chunks"]  
        comments = retrieved_content["comments"]
        holder = await keyword_retriever.ainvoke(question)
        chunks += holder
        
    return {**state, "chunks": chunks , "comments": comments}




def add_page_numbers_to_chunks(state: GraphState):
    """Add page numbers to chunk metadata if available."""
    files_address = settings.files_dir
    #TODO: implement this function to add page numbers to chunks based on file paths
    return state

async def generate_answer(state: GraphState) -> GraphState:
    """Generate answer using retrieved documents."""
    question = state["question"]
    chunks = state["chunks"]
    comments = state["comments"]
    
    # Create prompt template
    template = """Use ONLY the provided context to answer the question. Cite sources using [chunk:id] or [comment:id].

Context:
{context}

Question: {question}

Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    
    # Use centralized LLM client
    # Initialize LLM
    llm = ChatOpenAI(
        base_url=settings.openai_base_url,
        model="gemma3:27b",
        temperature=0.1,
        openai_api_key=settings.openai_api_key
    )    
    # Generate answer
    chain = prompt | llm
    
    context = "\n\n".join(f"context Id:{chunk.id}\ncontext content:{chunk.content}" for chunk in chunks)
    context += "\n\n" + "\n\n".join(f"Comment Id:{comment.id}\ncomment content:{comment.content}" for comment in comments)
    
    # print("Generated Context for LLM:")
    # print(context)
    # print("Question:")
    # print(question)
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
    
    workflow.add_edge("generate", "end")
    
    # Set entry point
    workflow.set_entry_point("retrieve")
    workflow.set_finish_point("end")
    # Compile
    return workflow.compile()
