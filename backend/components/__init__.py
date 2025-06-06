from components.embedding import JinaAPIEmbeddings
from settings import get_settings

settings = get_settings()

embeddings = JinaAPIEmbeddings(api_key=settings.jina_api_key)
