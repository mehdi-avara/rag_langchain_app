from typing import List, Dict, Any, Optional
from langchain_chroma import Chroma
from settings import get_settings
from components import embeddings

settings = get_settings()


class ChromaStore:
    def __init__(self):
        self.embeddings = embeddings
        self._store = None

    @property
    def store(self) -> Chroma:
        if self._store is None:
            self._store = Chroma(
                persist_directory=settings.chroma_persist_dir,
                embedding_function=self.embeddings,
                collection_name="chunks"
            )
        return self._store

    async def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        """Add texts to Chroma store."""
        self.store.add_texts(
            texts=texts,
            metadatas=metadatas,
            ids=ids
        )
        self.store.persist()

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get retriever interface."""
        if search_kwargs is None:
            search_kwargs = {"k": 6}
        return self.store.as_retriever(search_kwargs=search_kwargs)