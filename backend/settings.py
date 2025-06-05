from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    jina_api_key: str

    # Database URLs
    postgres_url: str

    # Vector DB
    elastic_host: str
    chroma_persist_dir: str

    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 4

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 