import requests
from langchain.embeddings.base import Embeddings

class JinaAPIEmbeddings(Embeddings):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "jina-embeddings-v3"
        self.api_url = "http://10.0.0.10:8088/v1/embeddings"
        self.task = "text-matching"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {

            "input": texts
        }
        response = requests.post(self.api_url, headers=headers, json=payload)
        response.raise_for_status()
        
        return [item["embedding"] for item in response.json()["data"]]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @property
    def embedding(self):
        return self
