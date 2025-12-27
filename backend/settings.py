from pydantic_settings import BaseSettings
from typing import Optional, List
from functools import lru_cache


class Settings(BaseSettings):


    # Database URLs
    postgres_url: str

    # Default user
    default_username: str
    default_password: str
    default_firstname: str

    cors_allow_origins: List[str] = []
    
    # API Keys
    openai_api_key: str
    openai_base_url: str = "http://10.0.0.10:11434/v1"
    # openai_model: str =  "openai.gpt-oss-20b-1:0"
    openai_model: str =  "gpt-oss-120b"
    
    #embedding_base_url: str
    embedding_base_url: str = "http://10.0.0.10:8088/v1"
    embedding_api_key: str = "None"
    
    # LLM Configuration
    llm_model: str = "gemma3:27b"  # Default model for answer generation
    llm_temperature: float = 0.1  # Default temperature for answer generation
    llm_rewrite_model: str = "gemma3:27b"  # Model for query rewriting
    llm_rewrite_temperature: float = 0.3  # Temperature for query rewriting
    llm_max_tokens: int = 150  # Max tokens for query rewriting


    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 24

    jina_api_key: str
    
    
    files_dir: str = "uploaded_files"

    mineru_running_address: str = "./mineru"

    redis_url: str = "redis://localhost:6379/0"
    
    base_url : str = "https://porsaapi.javidanparto.com"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 