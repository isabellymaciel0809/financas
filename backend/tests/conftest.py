import os

# Precisa vir antes de importar o app: banco em memória e nenhum LLM real.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LLM_PROVIDER"] = "none"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.deps import get_llm_provider  # noqa: E402
from app.main import app  # noqa: E402
from app.services.categorizer.llm import (  # noqa: E402
    CategoryOption,
    LLMError,
    LLMItem,
    Suggestion,
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

    def is_available(self) -> bool:
        return not self.fail

    def categorize(self, items: list[LLMItem], categories: list[CategoryOption]):
        self.calls.append(items)
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


@pytest.fixture
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    seed_categories(session)
    yield session
    session.close()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(db, fake_llm):
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
