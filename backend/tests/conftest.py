import os
import tempfile

# Precisa vir antes de importar o app: banco em memória, nenhum LLM real e uploads temporários.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LLM_PROVIDER"] = "none"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="financas-uploads-")
os.environ["RESUME_QUEUES_ON_STARTUP"] = "false"  # testado diretamente em test_retomada.py

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import require_user  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.deps import get_llm_provider  # noqa: E402
from app.login_limit import login_limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.services.categorizer.llm import (  # noqa: E402
    CategoryOption,
    ChatResult,
    LLMError,
    LLMItem,
    Suggestion,
    ToolCall,
)
from app.services.ingest import seed_categories  # noqa: E402


class FakeLLM:
    """LLM determinístico para testes: devolve respostas configuradas por descrição."""

    name = "fake"
    model = "fake-1"

    def __init__(self, answers: dict[str, tuple[str, float]] | None = None, fail: bool = False):
        self.answers = answers or {}
        self.fail = fail
        self.calls: list[list[LLMItem]] = []
        self.chat_script = []
        self.tool_results = []

    def is_available(self) -> bool:
        return not self.fail

    def categorize(self, items: list[LLMItem], categories: list[CategoryOption]):
        self.calls.append(items)
        self.offered = [c.name for c in categories]  # o que a LLM pôde escolher
        if self.fail:
            raise LLMError("LLM fora do ar")
        out = []
        for item in items:
            for needle, (category, confidence) in self.answers.items():
                if needle.lower() in item.description.lower():
                    out.append(
                        Suggestion(index=item.index, category=category, confidence=confidence)
                    )
                    break
        return out

    # Assistente: executa as chamadas de ferramenta roteirizadas e devolve os resultados.
    chat_script: list[tuple[str, dict]] = []
    tool_results: list[dict] = []

    def chat_with_tools(self, system, messages, tools, execute):
        if self.fail:
            raise LLMError("LLM fora do ar")
        self.last_system, self.last_messages = system, messages
        calls = []
        for name, arguments in self.chat_script:
            self.tool_results.append(execute(name, arguments))
            calls.append(ToolCall(name, arguments))
        return ChatResult(answer="resposta do fake", tool_calls=calls)


@pytest.fixture
def db():
    # Trava de segurança: se o app for importado antes deste arquivo (ex.: um script que importa
    # app.models e depois chama pytest.main), o engine aponta para o banco real e o drop_all
    # abaixo apagaria os dados. Já aconteceu; por isso a checagem.
    if str(engine.url) != "sqlite://":
        pytest.exit(
            f"Testes recusados: o banco é {engine.url}, não o banco em memória. Rode o pytest "
            "direto, sem importar o app antes.",
            returncode=1,
        )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    seed_categories(session)
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _limite_de_login_zerado():
    """O limite de tentativas fica em memória: cada teste começa sem erros contados."""
    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(db, fake_llm):
    """Cliente já logado: os testes de funcionalidade não precisam repetir o login."""
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    app.dependency_overrides[require_user] = lambda: User(id=0, username="teste", is_admin=True)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db, fake_llm):
    """Cliente sem login, para testar a autenticação de verdade."""
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
