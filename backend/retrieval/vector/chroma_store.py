import requests
from typing import List, Dict, Any, Optional
from langchain_community.vectorstores import Chroma
from settings import get_settings

settings = get_settings()

class JinaAPIEmbeddings:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "jina-embeddings-v3"
        self.api_url = "https://api.jina.ai/v1/embeddings"
        self.task = "text-matching"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "task": self.task,
            "input": texts
        }
        response = requests.post(self.api_url, headers=headers, json=payload)
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

class ChromaStore:
    def __init__(self):
        self.embeddings = JinaAPIEmbeddings(api_key=settings.jina_api_key)
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