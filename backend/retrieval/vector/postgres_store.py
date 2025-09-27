from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.models import Chunk, Document
from components.embedding import JinaAPIEmbeddings
from settings import get_settings
from langchain_core.documents import Document


settings = get_settings()


class PostgresVectorStore:
    def __init__(self, db: Session):
        self.db = db
        self.embeddings = JinaAPIEmbeddings(api_key=settings.jina_api_key)

    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        """Add texts to PostgreSQL vector store."""
        # Generate embeddings for the texts
        embeddings_list = self.embeddings.embed_documents(texts)
        
        # Update existing chunks with embeddings
        for i, (text, metadata, chunk_id) in enumerate(zip(texts, metadatas, ids)):
            chunk = self.db.query(Chunk).filter(Chunk.vdb_id == chunk_id).first()
            if chunk:
                chunk.embedding = embeddings_list[i]
        
        self.db.commit()
    
    def delete_by_doc_id(self, doc_id: str) -> None:
        """Delete all chunks related to a given doc_id."""
        # This is handled by the database cascade delete
        # when the document is deleted, so no action needed here
        pass
                
    def similarity_search(
        self,
        query: str,
        k: int = 6,
        doc_id: Optional[int] = None
    ) -> List[Tuple[Chunk, float]]:
        """Perform similarity search using PostgreSQL vector operations."""
        # Generate embedding for the query
        query_embedding = self.embeddings.embed_query(query)
        
        # Build the SQL query for vector similarity search
        # Format the embedding as a PostgreSQL vector string
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        if doc_id:
            # Search within a specific document
            sql = text(f"""
                SELECT c.*, 1 - (c.embedding <=> '{embedding_str}'::vector) as similarity
                FROM chunks c
                WHERE c.doc_id = :doc_id 
                AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> '{embedding_str}'::vector
                LIMIT :k
            """)
            result = self.db.execute(sql, {
                'doc_id': doc_id,
                'k': k
            })
        else:
            # Search across all documents
            sql = text(f"""
                SELECT c.*, 1 - (c.embedding <=> '{embedding_str}'::vector) as similarity
                FROM chunks c
                WHERE c.embedding IS NOT NULL
                ORDER BY c.embedding <=> '{embedding_str}'::vector
                LIMIT :k
            """)
            result = self.db.execute(sql, {
                'k': k
            })
        
        # Convert results to Chunk objects with similarity scores
        results = []
        for row in result:
            chunk = self.db.query(Chunk).filter(Chunk.id == row.id).first()
            if chunk:
                results.append((chunk, row.similarity))
        
        return results

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None,
        doc_id: Optional[int] = None
    ) -> 'PostgresVectorRetriever':
        """Get retriever interface."""
        if search_kwargs is None:
            search_kwargs = {"k": 6}
        return PostgresVectorRetriever(
            vector_store=self,
            search_kwargs=search_kwargs,
            doc_id=doc_id
        )


class PostgresVectorRetriever:
    """Retriever interface for PostgreSQL vector store."""
    
    def __init__(
        self,
        vector_store: PostgresVectorStore,
        search_kwargs: Dict[str, Any],
        doc_id: Optional[int] = None
    ):
        self.vector_store = vector_store
        self.search_kwargs = search_kwargs
        self.doc_id = doc_id

    def get_relevant_documents(self, query: str) -> List[Dict[str, Any]]:
        """Get relevant documents for a query."""
        k = self.search_kwargs.get("k", 6)
        results = self.vector_store.similarity_search(
            query=query,
            k=k,
            doc_id=self.doc_id
        )
        
        # Convert to the format expected by LangChain
        documents = []
        for chunk, similarity in results:
            doc = Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "page_num": chunk.page_num,
                    "chunk_type": chunk.chunk_type,
                    "similarity": similarity
                }
            )
            documents.append(doc)        
        return documents

    def invoke(self, query: str) -> List[Dict[str, Any]]:
        """Invoke the retriever (alias for get_relevant_documents)."""
        return self.get_relevant_documents(query)
