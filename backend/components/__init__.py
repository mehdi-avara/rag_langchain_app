from typing import List

from components.embedding import JinaAPIEmbeddings
from settings import get_settings

settings = get_settings()

embeddings = JinaAPIEmbeddings(fail_soft=True)


def generate_embeddings_for_chunks(chunks: List[str]) -> List[List[float]]:
    return embeddings.embed_documents(chunks)
