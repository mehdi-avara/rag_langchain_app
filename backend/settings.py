from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):


    # Database URLs
    postgres_url: str

    # Default user
    default_username: str
    default_password: str

    # API Keys
    openai_api_key: str
    openai_base_url: str = "http://10.0.0.10:11434/v1"
    
    # LLM Configuration
    llm_model: str = "gemma3:27b"  # Default model for answer generation
    llm_temperature: float = 0.1  # Default temperature for answer generation
    llm_rewrite_model: str = "gemma3:27b"  # Model for query rewriting
    llm_rewrite_temperature: float = 0.3  # Temperature for query rewriting
    llm_max_tokens: int = 150  # Max tokens for query rewriting

    # Vector DB
    # elastic_host: str
    chroma_persist_dir: str

    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 744

    jina_api_key: str
    
    bm25_index_path: str = "data/bm25.pkl"
    
    files_dir: str = "uploaded_files"

    mineru_running_address: str = "./mineru"


    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 