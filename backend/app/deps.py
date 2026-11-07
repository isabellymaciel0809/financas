from functools import lru_cache

from app.config import get_settings
from app.services.categorizer.llm import LLMProvider, build_provider


@lru_cache
def _provider() -> LLMProvider | None:
    return build_provider(get_settings())


def get_llm_provider() -> LLMProvider | None:
    """Dependência do FastAPI; nos testes é substituída por um provedor falso."""
    return _provider()
