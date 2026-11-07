"""Provedores de LLM.

Cada provedor sabe fazer duas coisas:
- `categorize`: classificar transações em lote, com saída estruturada (JSON Schema);
- `chat_with_tools`: conversar usando ferramentas que consultam o banco (assistente).

Os provedores compartilham prompts, schemas e definições de ferramentas; só muda o protocolo.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Falha ao consultar o LLM. A categorização continua sem ele (degradação graciosa)."""


# --- Categorização ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMItem:
    index: int
    description: str
    amount_cents: int


@dataclass(frozen=True)
class CategoryOption:
    name: str
    kind: str  # "expense" | "income"
    description: str = ""


class Suggestion(BaseModel):
    index: int
    category: str
    confidence: float


class CategorizationOutput(BaseModel):
    results: list[Suggestion]


SYSTEM_PROMPT = """Você categoriza transações de extratos bancários brasileiros.

Para cada transação, identifique o tipo de estabelecimento ou de movimentação e escolha a \
categoria cuja descrição melhor combina. Saídas de dinheiro recebem categorias de saída e \
entradas recebem categorias de entrada; a exceção são estornos e reembolsos, que voltam para \
a categoria da compra original. Considere o contexto brasileiro: IFD = iFood, Pix e TED são \
transferências, e prefixos como PAG*, MP*, SumUp e Stone são só a maquininha de pagamento, \
não o estabelecimento. Use "Outros" apenas como último recurso.

Em "confidence", dê um número de 0 a 1: perto de 1 quando o estabelecimento é conhecido e \
inequívoco, e abaixo de 0.5 quando você estiver deduzindo pelo nome. Responda com um item em \
"results" para cada transação, usando o mesmo "index" recebido."""


def _money(cents: int) -> str:
    value = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'entrada' if cents > 0 else 'saída'} de R$ {value}"


def build_user_message(items: list[LLMItem], categories: list[CategoryOption]) -> str:
    """Texto em linhas simples: modelos pequenos lidam melhor com isso do que com JSON aninhado."""
    lines = ["Categorias:"]
    for c in categories:
        kind = "entrada" if c.kind == "income" else "saída"
        lines.append(f"- {c.name} ({kind})" + (f": {c.description}" if c.description else ""))
    lines += ["", "Transações:"]
    lines += [f'{i.index}. "{i.description}" ({_money(i.amount_cents)})' for i in items]
    return "\n".join(lines)


def categorization_schema(category_names: list[str]) -> dict[str, Any]:
    """JSON Schema da resposta com as categorias como enum: o modelo não pode inventar nomes."""
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "category": {"type": "string", "enum": category_names},
                        "confidence": {"type": "number"},
                    },
                    "required": ["index", "category", "confidence"],
                },
            }
        },
        "required": ["results"],
    }


# --- Conversa com ferramentas ----------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema dos argumentos


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)


# Recebe (nome da ferramenta, argumentos) e devolve um resultado serializável em JSON.
ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]
MAX_TOOL_STEPS = 6


class LLMProvider(Protocol):
    name: str
    model: str

    def is_available(self) -> bool: ...

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]: ...

    def chat_with_tools(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec],
        execute: ToolExecutor,
    ) -> ChatResult: ...


# --- Ollama ----------------------------------------------------------------------------------


class OllamaProvider:
    """LLM local via Ollama: gratuito, offline, os dados não saem da máquina."""

    name = "ollama"
    AVAILABILITY_TTL_SECONDS = 30.0

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._http = client or httpx.Client()
        self._availability: tuple[float, bool] | None = None

    def is_available(self) -> bool:
        # Cache curto: a checagem é feita a cada carregamento da página.
        now = time.monotonic()
        if self._availability and now - self._availability[0] < self.AVAILABILITY_TTL_SECONDS:
            return self._availability[1]
        try:
            response = self._http.get(f"{self.base_url}/api/tags", timeout=1.0)
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
            available = self.model in names or f"{self.model}:latest" in names
        except (httpx.HTTPError, ValueError):
            available = False
        self._availability = (now, available)
        return available

    def _chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http.post(
                f"{self.base_url}/api/chat",
                # keep_alive: mantém o modelo na memória entre chamadas (recarregar custa segundos).
                json={"model": self.model, "stream": False, "keep_alive": "15m", **body},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["message"]
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama indisponível em {self.base_url}: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise LLMError(f"Resposta inválida do Ollama: {exc}") from exc

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]:
        message = self._chat(
            {
                # Saída estruturada: o Ollama restringe a geração a este JSON Schema.
                "format": categorization_schema([c.name for c in categories]),
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_message(items, categories)},
                ],
            }
        )
        try:
            return CategorizationOutput.model_validate_json(message.get("content", "")).results
        except ValidationError as exc:
            raise LLMError(f"Resposta inválida do Ollama: {exc}") from exc

    def chat_with_tools(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec],
        execute: ToolExecutor,
    ) -> ChatResult:
        conversation: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        calls: list[ToolCall] = []
        for _ in range(MAX_TOOL_STEPS):
            message = self._chat(
                {"messages": conversation, "tools": ollama_tools, "options": {"temperature": 0}}
            )
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return ChatResult(answer=(message.get("content") or "").strip(), tool_calls=calls)

            conversation.append(
                {
                    "role": "assistant",
                    "content": message.get("content", ""),
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                result = execute(name, arguments)
                calls.append(ToolCall(name, arguments))
                conversation.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
        raise LLMError("O assistente fez consultas demais sem chegar a uma resposta.")


# --- Anthropic (Claude) ----------------------------------------------------------------------


class AnthropicProvider:
    """Claude via API da Anthropic (opcional e pago; só é usado com ANTHROPIC_API_KEY)."""

    name = "anthropic"
    # Se o modelo recusar a requisição, a API tenta outro modelo automaticamente.
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, api_key: str | None, model: str):
        import anthropic

        self._anthropic = anthropic
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

    def is_available(self) -> bool:
        return self._client is not None

    def _call(self, method: str, **kwargs: Any) -> Any:
        """Chama `client.beta.messages.<method>` traduzindo erros da API para LLMError."""
        if self._client is None:
            raise LLMError("ANTHROPIC_API_KEY não configurada.")
        anthropic = self._anthropic
        try:
            response = getattr(self._client.beta.messages, method)(
                model=self.model, betas=[self.FALLBACK_BETA], fallbacks="default", **kwargs
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
        if response.stop_reason == "max_tokens":
            raise LLMError("Resposta do Claude incompleta.")
        return response

    def categorize(
        self, items: list[LLMItem], categories: list[CategoryOption]
    ) -> list[Suggestion]:
        response = self._call(
            "parse",
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(items, categories)}],
            output_format=CategorizationOutput,
            # Classificação é uma tarefa simples: esforço baixo = mais rápido e barato.
            output_config={"effort": "low"},
        )
        if response.parsed_output is None:
            raise LLMError("Resposta do Claude incompleta.")
        return response.parsed_output.results

    def chat_with_tools(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec],
        execute: ToolExecutor,
    ) -> ChatResult:
        conversation: list[dict[str, Any]] = list(messages)
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        calls: list[ToolCall] = []
        for _ in range(MAX_TOOL_STEPS):
            response = self._call(
                "create",
                max_tokens=16000,
                system=system,
                tools=anthropic_tools,
                messages=conversation,
                output_config={"effort": "medium"},
            )
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text")
                return ChatResult(answer=text.strip(), tool_calls=calls)

            # O conteúdo volta inteiro (inclui blocos de raciocínio), como a API exige.
            conversation.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = execute(block.name, dict(block.input))
                calls.append(ToolCall(block.name, dict(block.input)))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                        "is_error": "erro" in result,
                    }
                )
            # Todos os resultados vão em uma única mensagem do usuário.
            conversation.append({"role": "user", "content": results})
        raise LLMError("O assistente fez consultas demais sem chegar a uma resposta.")


def build_provider(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds
        )
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    return None
