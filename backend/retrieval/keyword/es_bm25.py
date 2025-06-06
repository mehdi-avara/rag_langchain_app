from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
from langchain.schema import Document
from langchain_core.runnables import Runnable



class BM25Retriever(Runnable):
    """
    Lightweight in‑memory BM25 retriever for prototypes.

    * Stores every chunk’s raw text and metadata in local lists.
    * Builds a BM25Okapi index (rank_bm25) once new texts are added.
    * Provides an **async** `ainvoke` method that returns the top‑k chunks
      as `langchain.schema.Document` objects so the downstream pipeline
      remains unchanged.

    NOTE: Corpus must fit in RAM; not thread‑safe beyond a single process.
    """

    def __init__(self, k: int = 6):
        self.k = k
        self.texts: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []
        self.corpus_tokens: List[List[str]] = []
        self._bm25: BM25Okapi | None = None

    async def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str] | None = None,
    ) -> None:
        """
        Ingest a batch of chunk texts.

        Parameters
        ----------
        texts : list of chunk strings
        metadatas : list of dicts (must align with `texts`)
        ids : unused here but kept for API compatibility
        """
        for text, meta in zip(texts, metadatas):
            self.texts.append(text)
            self.metadatas.append(meta)
            self.corpus_tokens.append(text.lower().split())

        # Rebuild BM25 index each time—fast for prototype sizes.
        self._bm25 = BM25Okapi(self.corpus_tokens)

    async def ainvoke(self, query: str, **kwargs) -> List[Document]:
        """
        Rank stored chunks against the user query and
        return the top‑k as LangChain Document objects.
        """
        if not self._bm25 or not self.texts:
            return []

        query_tokens = query.lower().split()
        scores = self._bm25.get_scores(query_tokens)
        top_idx = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[: self.k]

        # Build Document objects expected by downstream code
        return [
            Document(page_content=self.texts[i], metadata=self.metadatas[i])
            for i in top_idx
        ]

    def invoke(self, input: str):
        raise NotImplementedError("BM25Retriever only supports async usage via `ainvoke`.")