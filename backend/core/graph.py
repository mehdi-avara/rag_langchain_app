from typing import List, Dict, Any
from fastapi import HTTPException
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from db.models import Document as DBDocument
from retrieval.vector.chroma_store import ChromaStore
from settings import get_settings
from retrieval.keyword.full_text_db import FullTextRetrieverFromDB

from langchain.tools import tool
from langchain.chains import LLMChain
from langchain.agents import initialize_agent, Tool, AgentType

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

template = """Use ONLY the provided context to answer the question. Cite sources using [chunk:id].

Context:
{context}

Question: {question}

Answer:"""

prompt = ChatPromptTemplate.from_template(template)

llm = ChatOpenAI(
    model="gpt-4",
    temperature=0.1,
    openai_api_key=settings.openai_api_key
)

llm_chain = LLMChain(llm=llm, prompt=prompt)

tools = [
    Tool(
        name="Retrieve Documents",
        func=retrieve_docs_tool,
        description="Use this tool to retrieve relevant documents given a question and route."
    ),
    Tool(
        name="Fetch Adjacent Chunks",
        func=fetch_adjacent_chunks_tool,
        description="Use this tool to fetch adjacent chunks or additional context documents."
    )
]

agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

async def answer_question_with_agent(question: str, route: str, mode: str, db: Session) -> Dict[str, Any]:
    """Run the agent to answer the question using the specified route and mode."""
    # Retrieve documents first
    docs = await retrieve_docs_tool(question=question, route=route, mode=mode, db=db)
    # Optionally fetch adjacent chunks or enrich docs
    enriched_docs = await fetch_adjacent_chunks_tool(docs=docs)
    # Prepare context for the LLM chain
    context = "\n\n".join(doc.page_content for doc in enriched_docs)
    # Run the LLM chain to generate answer
    answer = await llm_chain.ainvoke({
        "context": context,
        "question": question
    })
    # Extract citations
    citations = []
    for doc in enriched_docs:
        if "chunk_id" in doc.metadata:
            citations.append(doc.metadata["chunk_id"])
    return {
        "answer": answer.content.strip(),
        "citations": citations
    }