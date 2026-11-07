from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente (ou do arquivo .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./financas.db"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Provedor de LLM usado como última etapa da categorização.
    #   ollama    -> modelo local, gratuito (padrão)
    #   anthropic -> Claude via API (pago, opcional)
    #   none      -> apenas memória + regras, sem LLM
    llm_provider: Literal["ollama", "anthropic", "none"] = "ollama"
    # Lotes pequenos: modelos locais de 3B perdem itens no meio de listas longas.
    llm_batch_size: int = 10

    # 127.0.0.1 em vez de localhost: no Windows, "localhost" tenta IPv6 antes e fica lento.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 120.0

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
