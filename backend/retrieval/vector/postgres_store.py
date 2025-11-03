from typing import List, Dict, Any, Optional, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.models import Chunk, Document, Comment
from components.embedding import JinaAPIEmbeddings
from settings import get_settings
from langchain_core.documents import Document as LangchainDocument


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
        doc_ids: Optional[List[int]] = None
    ) -> List[Tuple[Chunk, float]]:
        """Perform similarity search using PostgreSQL vector operations."""
        # Generate embedding for the query
        query_embedding = self.embeddings.embed_query(query)
        # Build the SQL query for vector similarity search
        # Format the embedding as a PostgreSQL vector string
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        if doc_ids is not None:
            if isinstance(doc_ids, list) and len(doc_ids) > 0:
                # Search within a list of documents
                placeholders = ','.join([f':doc_id_{i}' for i in range(len(doc_ids))])
                sql = text(f"""
                    SELECT c.*, 1 - (c.embedding <=> '{embedding_str}'::vector) as similarity
                    FROM chunks c
                    WHERE c.doc_id IN ({placeholders})
                    AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> '{embedding_str}'::vector
                    LIMIT :k
                """)
                params = {f'doc_id_{i}': doc_id for i, doc_id in enumerate(doc_ids)}
                params['k'] = k
                result = self.db.execute(sql, params)

            else:
                raise ValueError(f"Invalid doc_ids type, {type(doc_ids)}")
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
    
    def similarity_search_comments(
        self,
        query: str,
        k: int = 6,
        doc_ids: Optional[List[int]] = None,
        chunk_id: Optional[int] = None,
    ) -> List[Tuple[Comment, float]]:
        # 1) embed query
        query_embedding = self.embeddings.embed_query(query)
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        params = {'k': k}
        filters = ["c.embedding IS NOT NULL"]
        if doc_ids:
            placeholders = ','.join([f':doc_id_{i}' for i in range(len(doc_ids))])
            filters.append(f"c.doc_id IN ({placeholders})")
            for i, doc_id in enumerate(doc_ids):
                params[f'doc_id_{i}'] = doc_id

        if chunk_id is not None:
            filters.append("c.chunk_id = :chunk_id")
            params["chunk_id"] = chunk_id

        where_clause = " AND ".join(filters)

        sql = text(f"""
            SELECT c.*, 1 - (c.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM comments c
            WHERE {where_clause}
            ORDER BY c.embedding <=> '{embedding_str}'::vector
            LIMIT :k
        """)

        result = self.db.execute(sql, params)

        out: List[Tuple[Comment, float]] = []
        for row in result:
            comment = self.db.query(Comment).filter(Comment.id == row.id).first()
            if comment:
                out.append((comment, row.similarity))
        return out

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None,
        doc_ids: Optional[List[int]] = None
    ) -> 'PostgresVectorRetriever':
        """Get retriever interface."""
        if search_kwargs is None:
            search_kwargs = {"k": 6}
        return PostgresVectorRetriever(
            vector_store=self,
            search_kwargs=search_kwargs,
            doc_ids=doc_ids
        )


class PostgresVectorRetriever:
    """Retriever interface for PostgreSQL vector store."""
    
    def __init__(
        self,
        vector_store: PostgresVectorStore,
        search_kwargs: Dict[str, Any],
        doc_ids: Optional[List[int]] = None
    ):
        self.vector_store = vector_store
        self.search_kwargs = search_kwargs
        self.doc_ids = doc_ids

    def get_relevant_documents(self, query: str) -> List[Dict[str, Any]]:
        """Get relevant documents for a query."""
        k = self.search_kwargs.get("k", 6)
        results = self.vector_store.similarity_search(
            query=query,
            k=k,
            doc_ids=self.doc_ids
        )
        
        # Convert to the format expected by LangChain
        chunks = []
        for chunk, similarity in results:
            if similarity > 0.5:
                #TODO: similarity check
                pass
            chunks.append(chunk)        
        return chunks

    def invoke(self, query: str) -> List[Dict[str, Any]]:
        """Invoke the retriever (alias for get_relevant_documents)."""
        return self.get_relevant_documents(query)
