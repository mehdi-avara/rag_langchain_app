from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_core.runnables import Runnable
from rank_bm25 import BM25Okapi
import numpy as np
import pickle
import os

from settings import get_settings

settings = get_settings()



class BM25Retriever(Runnable):
    """
    Lightweight in‑memory BM25 retriever for prototypes.

    * Stores every chunk's raw text and metadata in local lists.
    * Builds a BM25Okapi index (rank_bm25) once new texts are added.
    * Provides an **async** `ainvoke` method that returns the top‑k chunks
      as `langchain.schema.Document` objects so the downstream pipeline
      remains unchanged.

    NOTE: Corpus must fit in RAM; not thread‑safe beyond a single process.
    """

    def __init__(self, k: int = 40):
        self.k = k
        self.texts = []
        self.metadatas = []
        self._bm25 = None

    async def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]] = None,
        ids: List[str] = None
    ) -> None:
        """Add texts to the retriever."""
        if metadatas is None:
            metadatas = [{} for _ in texts]
        
        # Tokenize texts
        tokenized_texts = [text.lower().split() for text in texts]
        
        # Initialize or update BM25
        if self._bm25 is None:
            self._bm25 = BM25Okapi(tokenized_texts)
        else:
            self._bm25 = BM25Okapi(tokenized_texts + [text.lower().split() for text in self.texts])
        
        # Update stored texts and metadata
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)

    async def ainvoke(self, query: str, **kwargs) -> List[Document]:
        """
        Rank stored chunks against the user query and
        return the top‑k as LangChain Document objects.
        """
        if not self._bm25 or not self.texts:
            return []
        # Tokenize query
        query_tokens = query.lower().split()
        
        # Get scores for all documents
        scores = self._bm25.get_scores(query_tokens)
        
        # Get top k indices
        top_idx = np.argsort(scores)[-self.k:][::-1]
        
        # Build Document objects expected by downstream code
        return [
            Document(
                page_content=self.texts[i],
                metadata=self.metadatas[i]
            )
            for i in top_idx if scores[i] > 0  # Only return documents with positive scores
        ]

    def invoke(self, input: str):
        raise NotImplementedError("BM25Retriever only supports async usage via `ainvoke`.")

    def save(self, path: str = settings.bm25_index_path):
        with open(path, "wb") as f:
            pickle.dump({
                "texts": self.texts,
                "metadatas": self.metadatas,
                "bm25": self._bm25
            }, f)

    def load(self, path: str = settings.bm25_index_path):
        if not os.path.exists(path):
            return  # Nothing to load
        with open(path, "rb") as f:
            data = pickle.load(f)
            self.texts = data["texts"]
            self.metadatas = data["metadatas"]
            self._bm25 = data["bm25"]
_bm25_retriever_instance = None

 
def get_bm25_retriever() -> BM25Retriever:
    global _bm25_retriever_instance
    if _bm25_retriever_instance is None:
        _bm25_retriever_instance = BM25Retriever()
        _bm25_retriever_instance.load()  
    return _bm25_retriever_instance