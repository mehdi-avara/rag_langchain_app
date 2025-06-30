from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func
from langchain_core.documents import Document
from langchain_core.runnables import Runnable
from sqlalchemy.sql import text

from db.models import Chunk

class FullTextRetrieverFromDB(Runnable):
    """
    A retriever that performs full-text search using PostgreSQL on the
    'preprocessed_content' field of the Chunk model.
    
    The input query should already be preprocessed (e.g., normalized Persian).
    """

    def __init__(self, db: Session):
        """
        Initialize the retriever with a SQLAlchemy database session.
        :param db: SQLAlchemy session instance.
        """
        self.db = db
            
    async def ainvoke(self, query: str, **kwargs) -> List[Document]:
        results = (
            self.db.query(Chunk)
            .filter(
                func.to_tsvector('simple', Chunk.content)
                .op('@@')(func.plainto_tsquery('simple', query))
            )
            .all()
        )

        return [
            Document(
                page_content=chunk.content,
                metadata={
                    "id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "page_num": chunk.page_num,
                    "chunk_type": chunk.chunk_type,
                    "vdb_id": chunk.vdb_id,
                    "created_at": chunk.created_at.isoformat(),
                }
            )
            for chunk in results
        ]
        
        
    def invoke(self, query: str):
        """
        Synchronous call is not supported. Use ainvoke instead.
        """
        raise NotImplementedError("Use `ainvoke(query)` asynchronously.")