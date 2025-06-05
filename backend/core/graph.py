from typing import Dict, List, TypedDict, Annotated
from langgraph.graph import Graph, StateGraph
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.retrievers import RouterRetriever
from langchain.retrievers.document_compressors import DocumentCompressorPipeline
from langchain.retrievers.document_compressors.embeddings_filter import EmbeddingsFilter
from langchain.embeddings import HuggingFaceEmbeddings

from ..retrieval.keyword.es_bm25 import BM25Retriever
from ..retrieval.vector.chroma_store import ChromaStore
from ..settings import get_settings

settings = get_settings()

class GraphState(TypedDict):
    question: str
    route: str
    docs: List[Dict]
    answer: str
    citations: List[int]

def classify_question(state: GraphState) -> GraphState:
    """Classify question type and choose retrieval route."""
    question = state["question"]
    words = len(question.split())
    
    if words <= 3:
        route = "keyword"
    else:
        route = "hybrid"
    
    return {**state, "route": route}

async def retrieve_docs(state: GraphState) -> GraphState:
    """Retrieve relevant documents based on route."""
    question = state["question"]
    route = state["route"]
    
    # Initialize retrievers
    keyword_retriever = BM25Retriever()
    vector_retriever = ChromaStore().as_retriever(
        search_kwargs={"k": 6}
    )
    
    # Create router
    router = RouterRetriever.from_llm(
        retrievers={
            "keyword": keyword_retriever,
            "vector": vector_retriever,
            "hybrid": DocumentCompressorPipeline.from_embeddings(
                embeddings=HuggingFaceEmbeddings(
                    model_name="jinaai/jina-embeddings-v3",
                    model_kwargs={'device': 'cpu'},
                    encode_kwargs={'normalize_embeddings': True}
                ),
                base_retriever=keyword_retriever
            )
        },
        default_retriever="hybrid"
    )
    
    # Retrieve documents
    docs = await router.ainvoke(question)
    return {**state, "docs": docs}

async def generate_answer(state: GraphState) -> GraphState:
    """Generate answer using retrieved documents."""
    question = state["question"]
    docs = state["docs"]
    
    # Create prompt template
    template = """Use ONLY the provided context to answer the question. Cite sources using [chunk:id].

Context:
{context}

Question: {question}

Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    
    # Initialize LLM
    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0,
        openai_api_key=settings.openai_api_key
    )
    
    # Generate answer
    chain = prompt | llm
    result = await chain.ainvoke({
        "context": "\n\n".join(doc.page_content for doc in docs),
        "question": question
    })
    
    # Extract citations
    citations = []
    for doc in docs:
        if "chunk_id" in doc.metadata:
            citations.append(doc.metadata["chunk_id"])
    
    return {
        **state,
        "answer": result.content.strip(),
        "citations": citations
    }

def build_answer_graph() -> Graph:
    """Build and compile the answer generation graph."""
    workflow = StateGraph(GraphState)
    
    # Add nodes
    workflow.add_node("classify", classify_question)
    workflow.add_node("retrieve", retrieve_docs)
    workflow.add_node("answer", generate_answer)
    
    # Add edges
    workflow.add_edge("classify", "retrieve")
    workflow.add_edge("retrieve", "answer")
    
    # Set entry and exit points
    workflow.set_entry_point("classify")
    workflow.set_finish_point("answer")
    
    return workflow.compile() 