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
    # Vector DB
    
    # elastic_host: str
    chroma_persist_dir: str

    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 744

    jina_api_key: str

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 