from typing import Dict, List, TypedDict, Annotated
from langgraph.graph import Graph, StateGraph
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors.embeddings_filter import EmbeddingsFilter
from langchain.retrievers.document_compressors import EmbeddingsFilter

from backend.db.models import Document
from retrieval.keyword.es_bm25 import BM25Retriever
from retrieval.vector.chroma_store import ChromaStore
from settings import get_settings
from components import embeddings

from langchain_core.runnables import Runnable
from typing import Any

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
    
    # Manual routing logic
    if route == "keyword":
        docs = await keyword_retriever.ainvoke(question)
    elif route == "vector":
        docs = await vector_retriever.ainvoke(question)
    elif route == "hybrid":
        # chroma = ChromaStore()
        # stored = chroma.store.get()
        # texts = stored["documents"]
        # metas = stored["metadatas"]
        # await keyword_retriever.add_texts(texts=texts, metadatas=metas)
        # hybrid_retriever = ContextualCompressionRetriever(
        #     base_compressor=EmbeddingsFilter(
        #         embeddings=embeddings.embedding,
        #         similarity_threshold=0.7
        #     ),
        #     base_retriever=keyword_retriever
        # )
        # docs = await hybrid_retriever.ainvoke(question)
        docs = await vector_retriever.ainvoke(question)
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
        model="gpt-4o",
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
            enriched_doc = Document(
                page_content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "enriched": True,
                    "enrichment_type": self.enrichment_type
                }
            )
            enriched_docs.append(enriched_doc)
        
        return {**state, "docs": enriched_docs}

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

def build_answer_graph() -> Graph:
    workflow = StateGraph(GraphState)
    
    # Initialize tools
    document_enricher = DocumentEnricher(enrichment_type="semantic")
    
    # Add nodes
    workflow.add_node("classify", classify_question)
    workflow.add_node("retrieve", retrieve_docs)
    workflow.add_node("enrich", document_enricher.ainvoke)
    workflow.add_node("generate", generate_answer)
    
    # Add edges with conditional routing
    workflow.add_conditional_edges(
        "classify",
        lambda x: x["route"],
        {
            "keyword": "retrieve",
            "hybrid": "enrich"
        }
    )
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("enrich", "generate")
    
    workflow.set_entry_point("classify")
    workflow.set_finish_point("generate")
    
    return workflow.compile()