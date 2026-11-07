"""Provedores de LLM para categorização. Todos compartilham o mesmo prompt e o mesmo schema."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Falha ao consultar o LLM. A categorização continua sem ele (degradação graciosa)."""


@dataclass(frozen=True)
class LLMItem:
    index: int
    description: str
    amount_cents: int


@dataclass(frozen=True)
class CategoryOption:
    name: str
    kind: str  # "expense" | "income"


class Suggestion(BaseModel):
    index: int
    category: str
    confidence: float


class CategorizationOutput(BaseModel):
    results: list[Suggestion]


SYSTEM_PROMPT = """Você categoriza transações de extratos bancários brasileiros.

Para cada transação, escolha exatamente uma categoria da lista fornecida, copiando o nome \
exatamente como aparece. Valores negativos são saídas de dinheiro e devem receber uma \
categoria do tipo "expense"; valores positivos são entradas e devem receber uma categoria do \
tipo "income", exceto estornos e reembolsos, que podem voltar para a categoria da despesa \
original. Use o nome do estabelecimento e o contexto brasileiro (siglas como IFD = iFood, \
PIX, TED, maquininhas como PAG*, SumUp, Stone). Se não houver pistas suficientes, use \
"Outros" para saídas e "Renda extra" para entradas, com confiança baixa.

Informe em "confidence" um número de 0 a 1 indicando sua certeza. Responda com um item em \
"results" para cada transação, usando o mesmo "index" recebido."""


def build_user_message(items: list[LLMItem], categories: list[CategoryOption]) -> str:
    payload = {
        "categorias": [{"nome": c.name, "tipo": c.kind} for c in categories],
        "transacoes": [
            {"index": i.index, "descricao": i.description, "valor": i.amount_cents / 100}
            for i in items
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


class LLMProvider(Protocol):
    name: str
    model: str

    def is_available(self) -> bool: ...

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]: ...


class OllamaProvider:
    """LLM local via Ollama: gratuito, offline, os dados não saem da máquina."""

    name = "ollama"

    AVAILABILITY_TTL_SECONDS = 30.0

    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._availability: tuple[float, bool] | None = None

    def is_available(self) -> bool:
        # Cache curto: a checagem é feita a cada carregamento da página.
        now = time.monotonic()
        if self._availability and now - self._availability[0] < self.AVAILABILITY_TTL_SECONDS:
            return self._availability[1]
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=1.0)
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
            available = self.model in names or f"{self.model}:latest" in names
        except (httpx.HTTPError, ValueError):
            available = False
        self._availability = (now, available)
        return available

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]:
        body = {
            "model": self.model,
            "stream": False,
            # Saída estruturada: o Ollama restringe a geração a este JSON Schema.
            "format": CategorizationOutput.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(items, categories)},
            ],
        }
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            response.raise_for_status()
            content = response.json()["message"]["content"]
            return CategorizationOutput.model_validate_json(content).results
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama indisponível em {self.base_url}: {exc}") from exc
        except (KeyError, ValidationError) as exc:
            raise LLMError(f"Resposta inválida do Ollama: {exc}") from exc


class AnthropicProvider:
    """Claude via API da Anthropic (opcional e pago; só é usado com ANTHROPIC_API_KEY)."""

    name = "anthropic"

    def __init__(self, api_key: str | None, model: str):
        import anthropic

        self._anthropic = anthropic
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

    def is_available(self) -> bool:
        return self._client is not None

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]:
        if self._client is None:
            raise LLMError("ANTHROPIC_API_KEY não configurada.")
        anthropic = self._anthropic
        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(items, categories)}],
                output_format=CategorizationOutput,
                # Classificação é uma tarefa simples: esforço baixo = mais rápido e barato.
                output_config={"effort": "low"},
                # Se o modelo recusar a requisição, a API tenta outro modelo automaticamente.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Chave da Anthropic inválida.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de requisições da Anthropic atingido.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Erro da API Anthropic ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Sem conexão com a API da Anthropic.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("O modelo recusou a requisição.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("Resposta do Claude incompleta.")
        return response.parsed_output.results


def build_provider(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds
        )
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    return None
