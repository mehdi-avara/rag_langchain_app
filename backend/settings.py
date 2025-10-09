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
    openai_base_url: str = "http://10.0.0.10:8085/v1"

    # Vector DB
    # elastic_host: str
    chroma_persist_dir: str

    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 744

    jina_api_key: str
    
    bm25_index_path: str = "data/bm25.pkl"
    
    files_dir: str = "uploaded_files"  # Relative to project root


    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 