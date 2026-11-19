from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "HealthGuard AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'healthguard.db'}"

    # LLM Provider Configuration ("ollama" for local dev, "groq" for cloud deployment)
    LLM_PROVIDER: str = "ollama"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "llama3.1"

    # Groq Cloud Inference (used when LLM_PROVIDER=groq)
    GROQ_API_KEY: Optional[str] = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    ALLOW_CLOUD_PERSONAL_DATA: bool = False

    # Embedding & Persistent Storage Paths
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_LOCAL_FILES_ONLY: bool = False
    VECTOR_DB_PATH: str = str(PROJECT_ROOT / "data" / "vector_db")
    UPLOAD_DIR: str = str(PROJECT_ROOT / "storage" / "medical_reports")

    # CORS Configuration (comma-separated origins)
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    CORS_ORIGIN_REGEX: Optional[str] = None

    # Background reminder worker toggle
    ENABLE_REMINDER_WORKER: bool = True

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql://" + value[len("postgres://"):]
        return value

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def _normalize_llm_provider(cls, value: str) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("ollama", "groq"):
                return normalized
        return "ollama"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [
            origin.strip().rstrip("/")
            for origin in (self.CORS_ORIGINS or "").split(",")
            if origin.strip()
        ]
        return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
