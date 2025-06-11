from typing import Dict, List, TypedDict, Tuple
from fastapi import HTTPException
from langgraph.graph import Graph, StateGraph
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from db.models import Document as DBDocument
from retrieval.vector.chroma_store import ChromaStore
from settings import get_settings
from retrieval.keyword.es_bm25 import get_bm25_retriever


from langchain_core.runnables import Runnable
from typing import Any

settings = get_settings()

class GraphState(TypedDict):
    question: str
    route: str
    docs: List[Document]
    answer: str
    citations: List[int]
    mode: str  # Can be "preview" or "full"

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
    mode = state.get("mode", "full")  # Default to full mode if not specified
    
    # Initialize retrievers
    keyword_retriever = get_bm25_retriever()
    vector_retriever = ChromaStore().as_retriever(
        search_kwargs={"k": 6 if mode == "full" else 3}  # Use fewer results for preview
    )
    
    # Manual routing logic
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
        temperature=0.1,
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

class DocumentEnricher(Runnable):
    """A tool that enriches documents with additional metadata."""
    
    def __init__(self, enrichment_type: str):
        self.enrichment_type = enrichment_type
    
    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        docs = state["docs"]
        enriched_docs = []
        
        for doc in docs:
            # Add your enrichment logic here
            enriched_doc = DBDocument(
                page_content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "enriched": True,
                    "enrichment_type": self.enrichment_type
                }
            )
            enriched_docs.append(enriched_doc)
        
        return {**state, "docs": enriched_docs}
    
    def invoke(self, input: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous version of ainvoke."""
        raise NotImplementedError("DocumentEnricher only supports async usage via `ainvoke`.")

class MyCustomTool(Runnable):
    def __init__(self, some_param: str):
        self.some_param = some_param
    
    async def ainvoke(self, input: str, **kwargs) -> Dict[str, Any]:
        # Your tool's logic here
        result = await self._process_input(input)
        return {"result": result}
    
    async def _process_input(self, input: str):
        # Implement your processing logic
        pass

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
        return "generate" if state.get("mode", "full") == "full" else "end"
    
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

async def build_answer_graph_with_id(doc_id: int, question: str, db: Session) -> Tuple[str, List[Dict], float]:
    """Build answer graph for a specific document."""
    # Get document
    doc = db.query(DBDocument).filter(DBDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Initialize graph
    graph = build_answer_graph()
    
    # Run graph
    result = await graph.ainvoke({
        "question": question,
        "route": "hybrid",
        "docs": [],
        "answer": "",
        "citations": [],
        "mode": "full"
    })
    
    return result["answer"], result["citations"], 1.0  # Confidence score