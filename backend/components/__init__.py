from typing import List

from components.embedding import JinaAPIEmbeddings
from settings import get_settings

settings = get_settings()

embeddings = JinaAPIEmbeddings()


def generate_embeddings_for_chunks(chunks: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of text chunks."""
    return embeddings.embed_documents(chunks)