import httpx

from app.services.categorizer.llm import (
    CategoryOption,
    LLMItem,
    OllamaProvider,
    build_user_message,
    categorization_schema,
)


def test_mensagem_descreve_categorias_e_sinal_por_extenso():
    text = build_user_message(
        [LLMItem(0, "PARAMOUNT+", -1990), LLMItem(1, "Pix recebido - Cliente", 123456)],
        [
            CategoryOption("Assinaturas", "expense", "streaming"),
            CategoryOption("Renda extra", "income"),
        ],
    )
    assert "- Assinaturas (saída): streaming" in text
    assert "- Renda extra (entrada)" in text
    assert '0. "PARAMOUNT+" (saída de R$ 19,90)' in text
    assert '1. "Pix recebido - Cliente" (entrada de R$ 1.234,56)' in text


def test_schema_restringe_categorias():
    schema = categorization_schema(["Mercado", "Outros"])
    item = schema["properties"]["results"]["items"]
    assert item["properties"]["category"]["enum"] == ["Mercado", "Outros"]


def _ollama(handler) -> OllamaProvider:
    provider = OllamaProvider(
        "http://ollama", "qwen2.5:3b", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.AVAILABILITY_TTL_SECONDS = 0  # sem cache: cada chamada consulta de novo
    return provider


def _tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_ollama_disponivel_so_com_o_modelo_baixado():
    assert _ollama(lambda request: _tags("qwen2.5:3b")).is_available()
    assert not _ollama(lambda request: _tags("llama3.2:1b")).is_available()


def test_ollama_fora_do_ar_fica_indisponivel():
    def handler(request):
        raise httpx.ConnectError("conexão recusada", request=request)

    assert not _ollama(handler).is_available()


def test_ollama_ocupado_nao_e_marcado_como_offline():
    """Gerando uma resposta na CPU, o Ollama demora a listar os modelos. Antes, isso o marcava
    como offline e o app recusava a categorização com o Ollama funcionando."""
    busy = False

    def handler(request):
        if busy:
            raise httpx.ReadTimeout("demorou", request=request)
        return _tags("qwen2.5:3b")

    provider = _ollama(handler)
    assert provider.is_available()
    busy = True
    assert provider.is_available()  # mantém o último resultado: estava no ar
