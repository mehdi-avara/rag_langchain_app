import requests
from langchain.embeddings.base import Embeddings
from settings import get_settings

settings = get_settings()

class JinaAPIEmbeddings(Embeddings):
    def __init__(self):
        self.api_key = settings.jina_api_key
        self.model = settings.embedding_model
        self.api_url = settings.embedding_base_url
        self.task = "text-matching"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "input": texts
        }

        response = requests.post(self.api_url, headers=headers, json=payload)
        response.raise_for_status()

        result = response.json()

        return result["result"]["data"]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @property
    def embedding(self):
        return self
