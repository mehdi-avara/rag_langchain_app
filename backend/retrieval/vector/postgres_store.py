from typing import List, Dict, Any, Optional, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import text
from Models import Chunk, Document, Comment
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
        query_embedding = self.embeddings.embed_query(query)
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        filters = ["c.embedding IS NOT NULL"]
        params: Dict[str, Any] = {"k": k, "query_vec": embedding_str}

        if doc_ids:
            placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
            filters.append(f"c.doc_id IN ({placeholders})")
            for i, did in enumerate(doc_ids):
                params[f"doc_id_{i}"] = did

        where_clause = " AND ".join(filters)

        sql = text(f"""
            SELECT c.id AS id,
                (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
            FROM chunks c
            WHERE {where_clause}
            ORDER BY similarity DESC
            LIMIT :k
        """)

        rows = self.db.execute(sql, params).fetchall()
        if not rows:
            return []

        ids_in_order = [r.id for r in rows]

        chunks = (
            self.db.query(Chunk)
            .filter(Chunk.id.in_(ids_in_order))
            .all()
        )
        chunks_by_id = {c.id: c for c in chunks}

        return [(chunks_by_id[r.id], r.similarity) for r in rows if r.id in chunks_by_id]


    def similarity_search_comments(
            self,
            query: str,
            k: int = 6,
            comment_ids: Optional[List[int]] = None
        ) -> List[Tuple[Comment, float]]:
            # 1) embed query
            query_embedding = self.embeddings.embed_query(query)
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

            # 2) build filters + params
            filters = ["c.embedding IS NOT NULL"]
            params: dict = {
                "k": k,
                "query_vec": embedding_str,
            }

            if comment_ids:
                placeholders = ", ".join(f":id_{i}" for i in range(len(comment_ids)))
                filters.append(f"c.id IN ({placeholders})")
                for i,id in enumerate(comment_ids):
                    params[f"id_{i}"] = id

            where_clause = " AND ".join(filters)

            # 3) run cosine-sim query
            sql = text(f"""
                SELECT c.id AS id,
                    (-1 * (c.embedding <=> (:query_vec)::vector)) AS similarity
                FROM comments c
                WHERE {where_clause}
                ORDER BY similarity DESC
                LIMIT :k
            """)

            rows = self.db.execute(sql, params).fetchall()

            if not rows:
                return []

            # 4) load all comments in one go
            ids_in_order = [r.id for r in rows]
            comments = (
                self.db.query(Comment)
                .filter(Comment.id.in_(ids_in_order))
                .all()
            )
            comments_by_id = {c.id: c for c in comments}

            # 5) return in similarity order
            out: List[Tuple[Comment, float]] = []
            for r in rows:
                c = comments_by_id.get(r.id)
                if c is not None:
                    out.append((c, r.similarity))

            return out

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None,
        doc_ids: Optional[List[int]] = None,
        comment_ids: Optional[List[int]] = None
    ) -> 'PostgresVectorRetriever':
        """Get retriever interface."""
        if search_kwargs is None:
            search_kwargs = {"k": 6}
        return PostgresVectorRetriever(
            vector_store=self,
            search_kwargs=search_kwargs,
            doc_ids=doc_ids,
            comment_ids=comment_ids
            
        )


class PostgresVectorRetriever:
    """Retriever interface for PostgreSQL vector store."""
    
    def __init__(
        self,
        vector_store: PostgresVectorStore,
        search_kwargs: Dict[str, Any],
        doc_ids: Optional[List[int]] = None,
        comment_ids: Optional[List[int]] = None,
        chunk_ids: Optional[List[int]] = None
    ):
        self.vector_store = vector_store
        self.search_kwargs = search_kwargs
        self.doc_ids = doc_ids
        self.comment_ids = comment_ids
        self.chunk_ids = chunk_ids

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

    def get_relevant_comments(self, query: str) -> List[Dict[str, Any]]:
        """Get relevant comments for a query."""
        k = self.search_kwargs.get("k", 6)
        results = self.vector_store.similarity_search_comments(
            query=query,
            k=k,
            comment_ids=self.comment_ids
        )
        # Convert to the format expected by LangChain
        comments = []
        for comment, similarity in results:
            if similarity > 0.5:
                #TODO: similarity check
                pass
            comments.append(comment)        
        return comments

    def invoke(self, query: str) -> List[Dict[str, Any]]:
        """Invoke the retriever (alias for get_relevant_documents)."""
        retrieved_contents = {}
        retrieved_contents["chunks"] = self.get_relevant_documents(query)
        retrieved_contents["comments"] = self.get_relevant_comments(query)
        return retrieved_contents
