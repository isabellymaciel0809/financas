from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_llm_provider
from app.services.assistant import ask
from app.services.categorizer.llm import LLMError, LLMProvider

router = APIRouter(prefix="/assistant", tags=["assistente"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    # A conversa fica no navegador; o backend é stateless e recebe o histórico a cada pergunta.
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCallOut]
    # Valores em R$ da resposta que não aparecem nos dados consultados (possível alucinação).
    unverified_values: list[str]


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    if payload.messages[-1].role != "user":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A última mensagem deve ser do usuário."
        )
    if provider is None or not provider.is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "O assistente precisa de uma LLM. Instale o Ollama e baixe o modelo configurado.",
        )
    try:
        answer = ask(db, provider, [m.model_dump() for m in payload.messages])
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    result = answer.result
    return ChatResponse(
        answer=result.answer or "Não consegui formular uma resposta. Tente reformular a pergunta.",
        tool_calls=[ToolCallOut(name=c.name, arguments=c.arguments) for c in result.tool_calls],
        unverified_values=answer.unverified_values,
    )
