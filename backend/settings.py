from functools import lru_cache
from typing import List

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_IP: str
    POSTGRES_PORT: int = 5432

    @computed_field
    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_IP}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    default_username: str
    default_password: str
    default_firstname: str

    cors_allow_origins: List[str] = [
        "https://porsa.javidanparto.com",
        "http://localhost:5000",
    ]

    llm_model: str = "gemma3:27b"
    llm_temperature: float = 0.1
    llm_rewrite_model: str = "gemma3:27b"
    llm_rewrite_temperature: float = 0.3
    llm_max_tokens: int = 150

    jwt_secret: str
    jwt_exp_hours: int = 24

    files_dir: str = "uploaded_files"
    mineru_running_address: str = "./mineru"
    redis_url: str = "redis://localhost:6379/0"
    base_url: str = "https://porsaapi.javidanparto.com"

    request_log_file: str = "logs/api.log"
    request_log_max_chars: int = 1024
    request_log_max_file_size: int = 10 * 1024 * 1024
    request_log_backup_count: int = 5

    STT_URL: str = "http://localhost:8010"

    openai_api_key: str
    openai_base_url: str = "http://10.0.0.10:11434/v1"
    openai_model: str = "gpt-oss-120b"

    embedding_dim: int = 1024
    embedding_model: str = "jina-embeddings-v3"
    embedding_base_url: str = "http://10.0.0.10:8088/v1"
    embedding_api_key: str = "None"
    jina_api_key: str


@lru_cache()
def get_settings() -> Settings:
    return Settings()