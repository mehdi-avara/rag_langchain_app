from pydantic_settings import BaseSettings
from typing import Literal, Optional, List
from functools import lru_cache
from pydantic import computed_field
from pathlib import Path


class Settings(BaseSettings):


    BASE_DIR: Path = Path(__file__).resolve().parent
    
    @computed_field
    @property
    def STATIC_DIR(self) -> Path:
        return self.BASE_DIR / "static"
    
    # Database URLs
    
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_IP: str
    
    @computed_field
    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_IP}:5432/{self.POSTGRES_DB}"
    
    
    # Default user
    default_username: str
    default_password: str
    default_firstname: str

    cors_allow_origins: List[str] = ["https://porsa.mahta-tech.com","http://localhost:5000"]
    

    
    # LLM Configuration
    llm_model: str = "gemma3:27b"  # Default model for answer generation
    llm_temperature: float = 0.1  # Default temperature for answer generation
    llm_rewrite_model: str = "gemma3:27b"  # Model for query rewriting
    llm_rewrite_temperature: float = 0.3  # Temperature for query rewriting
    llm_max_tokens: int = 150  # Max tokens for query rewriting


    # JWT
    jwt_secret: str
    jwt_exp_hours: int = 24

    # Public tenant self-registration is denied unless the deployment
    # explicitly opts into the open policy. No invitation or email-
    # verification workflow is silently assumed by this setting.
    self_registration_mode: Literal["disabled", "open"] = "disabled"
    self_registration_rate_window_seconds: int = 3600
    self_registration_rate_max_per_email: int = 5
    self_registration_rate_max_global: int = 25

    
    
    files_dir: str = "uploaded_files"

    mineru_running_address: str = "./mineru"

    redis_url: str = "redis://localhost:6379/0"
    
    base_url : str = "https://porsaapi.mahta-tech.com"
    
    # Logging
    request_log_file: str = "logs/api.log"
    request_log_max_chars: int = 1024
    request_log_max_file_size: int = 10 * 1024 * 1024  # 10 MB
    request_log_backup_count: int = 5
    # Assistant event payloads are intentionally bounded and redacted before
    # they reach either PostgreSQL or operational logs.
    assistant_event_payload_max_bytes: int = 32 * 1024
    assistant_event_preview_chars: int = 256
    assistant_state_snapshot_max_bytes: int = 128 * 1024
    
    #services stt
    STT_URL: str = "http://localhost:8010"
    
    # services Chat_model 
    openai_api_key: str
    openai_base_url: str = "http://10.0.0.10:11434/v1"
    # openai_model: str =  "openai.gpt-oss-20b-1:0"
    openai_model: str =  "gpt-oss-120b"
    
    #services embedding_model
    embedding_dim: int = 1024
    embedding_model: str = "jina-embeddings-v3"
    
    embedding_base_url: str = "http://10.0.0.10:8088/v1"
    embedding_api_key: str = "None"
    jina_api_key: str
    
    BACKEND_PORT: int = 8001
    REDIS_PORT: int = 6379
    request_log_path: str = "/home/ubuntu/rag_langchain_app/backend/logs/"

    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_PUBLIC_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str = "minioadmin"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "porsa-assets"
    S3_REGION_NAME: str = "us-east-1"
    S3_USE_SSL: bool = False
    S3_UPLOAD_EXPIRES_SECONDS: int = 900
    S3_DOWNLOAD_EXPIRES_SECONDS: int = 300
    MAX_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024
    ALLOWED_UPLOAD_CONTENT_TYPES: str = "application/pdf,image/png,image/jpeg,image/webp,text/plain,application/zip,audio/mpeg,audio/wav,video/mp4"

    DEFAULT_COMPANY_NAME: str = "Javidan parto electron"
    DEFAULT_COMPANY_SLUG: str = "JPE"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings() 
