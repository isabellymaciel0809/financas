import json
from datetime import date

import httpx
import pytest

from app.models import Transaction
from app.services.assistant import TOOLS, Toolbox
from app.services.categorizer.llm import OllamaProvider
from app.services.categorizer.pipeline import categorize_transactions
from app.services.text import merchant_key

TODAY = date(2026, 10, 20)


@pytest.fixture
def toolbox(db):
    rows = [
        (date(2026, 9, 10), "Compra no débito - IFD*IFOOD", -5000),
        (date(2026, 10, 1), "Compra no débito - IFD*IFOOD", -4590),
        (date(2026, 10, 3), "Compra no débito - IFD*IFOOD", -3210),
        (date(2026, 10, 5), "Transferência recebida - Salário ACME", 650000),
        (date(2026, 10, 6), "Pagamento de boleto - Aluguel", -180000),
        (date(2026, 10, 8), "Pix enviado - Maria Oliveira", -12000),
    ]
    txs = [
        Transaction(
            date=d,
            description=desc,
            amount_cents=amount,
            merchant_key=merchant_key(desc),
            fingerprint=str(i),
        )
        for i, (d, desc, amount) in enumerate(rows)
    ]
    db.add_all(txs)
    db.flush()
    categorize_transactions(db, txs, None)
    db.commit()
    return Toolbox(db, today=TODAY)


def test_resumo_financeiro(toolbox):
    result = toolbox.execute(
        "resumo_financeiro", {"data_inicio": "2026-10-01", "data_fim": "2026-10-31"}
    )
    assert result["receitas"] == 6500.0
    assert result["despesas"] == 45.90 + 32.10 + 1800 + 120
    assert result["despesas_por_categoria"][0] == {
        "categoria": "Moradia",
        "total": 1800.0,
        "quantidade": 1,
    }
    alimentacao = next(
        c for c in result["despesas_por_categoria"] if c["categoria"] == "Alimentação"
    )
    assert alimentacao == {"categoria": "Alimentação", "total": 78.0, "quantidade": 2}
    # Sem categoria também aparece, para a LLM não "esconder" gastos.
    assert any(c["categoria"] == "Sem categoria" for c in result["despesas_por_categoria"])


def test_data_fim_inclusiva(toolbox):
    result = toolbox.execute(
        "resumo_financeiro", {"data_inicio": "2026-10-05", "data_fim": "2026-10-05"}
    )
    assert result["quantidade_transacoes"] == 1


def test_buscar_maiores_despesas(toolbox):
    result = toolbox.execute(
        "buscar_transacoes", {"tipo": "despesa", "ordem": "maiores", "limite": 2}
    )
    assert result["quantidade_encontrada"] == 5
    assert [t["valor"] for t in result["transacoes"]] == [-1800.0, -120.0]


def test_buscar_por_texto_soma_tudo_mesmo_com_limite(toolbox):
    result = toolbox.execute("buscar_transacoes", {"texto": "ifood", "limite": 1})
    assert result["quantidade_encontrada"] == 3
    assert result["mostrando"] == 1
    assert result["soma"] == -(50 + 45.90 + 32.10)


def test_categoria_aceita_sem_acento(toolbox):
    result = toolbox.execute("buscar_transacoes", {"categoria": "alimentacao"})
    assert result["quantidade_encontrada"] == 3


def test_erros_voltam_para_a_llm(toolbox):
    assert "não existe" in toolbox.execute("buscar_transacoes", {"categoria": "Pets"})["erro"]
    assert "inválidos" in toolbox.execute("resumo_financeiro", {"data_inicio": "ontem"})["erro"]
    assert "desconhecida" in toolbox.execute("apagar_tudo", {})["erro"]
    # Campos vazios que modelos pequenos às vezes mandam são ignorados.
    assert "erro" not in toolbox.execute("buscar_transacoes", {"categoria": "", "texto": None})


def test_evolucao_mensal(toolbox):
    result = toolbox.execute("evolucao_mensal", {"meses": 2})
    assert result["meses"] == [
        {"mes": "2026-09", "receitas": 0.0, "despesas": 50.0, "saldo": -50.0},
        {"mes": "2026-10", "receitas": 6500.0, "despesas": 1998.0, "saldo": 4502.0},
    ]


def test_loop_de_ferramentas_do_ollama(toolbox):
    """Simula o Ollama: primeiro pede uma ferramenta, depois responde com o resultado."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "buscar_transacoes", "arguments": {"texto": "ifood"}}}
                ],
            }
        else:
            tool_message = body["messages"][-1]
            total = json.loads(tool_message["content"])["soma"]
            message = {"role": "assistant", "content": f"Você gastou R$ {-total:.2f} no iFood."}
        return httpx.Response(200, json={"message": message})

    provider = OllamaProvider(
        "http://ollama", "qwen2.5:3b", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = provider.chat_with_tools(
        "sistema", [{"role": "user", "content": "Quanto gastei no iFood?"}], TOOLS, toolbox.execute
    )

    assert result.answer == "Você gastou R$ 128.00 no iFood."
    assert [c.name for c in result.tool_calls] == ["buscar_transacoes"]
    assert {t["function"]["name"] for t in requests[0]["tools"]} == {t.name for t in TOOLS}
    assert requests[1]["messages"][-1]["role"] == "tool"


def test_api_chat(client, fake_llm):
    fake_llm.chat_script = [("evolucao_mensal", {"meses": 3})]
    response = client.post(
        "/api/assistant/chat", json={"messages": [{"role": "user", "content": "Como estou?"}]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "resposta do fake"
    assert body["tool_calls"] == [{"name": "evolucao_mensal", "arguments": {"meses": 3}}]
    assert "Alimentação" in fake_llm.last_system  # categorias reais vão no prompt


def test_api_chat_sem_llm(client, fake_llm):
    fake_llm.fail = True
    response = client.post(
        "/api/assistant/chat", json={"messages": [{"role": "user", "content": "Oi"}]}
    )
    assert response.status_code == 503


def test_api_chat_ultima_mensagem_precisa_ser_do_usuario(client):
    response = client.post(
        "/api/assistant/chat", json={"messages": [{"role": "assistant", "content": "Oi"}]}
    )
    assert response.status_code == 422
