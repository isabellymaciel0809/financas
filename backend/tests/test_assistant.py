import json
from datetime import date

import httpx
import pytest

from app.models import Transaction
from app.services.assistant import (
    TOOLS,
    Toolbox,
    ask,
    brl,
    money_values,
    period_from_text,
    resolve_period,
)
from app.services.categorizer.llm import ChatResult, OllamaProvider, ToolCall
from app.services.categorizer.pipeline import categorize_transactions
from app.services.text import merchant_key

TODAY = date(2026, 10, 20)


@pytest.fixture
def toolbox(db):
    rows = [
        (date(2026, 9, 10), "Compra no débito - IFD*IFOOD", -5000),
        (date(2026, 9, 12), "Compra no débito - UBER *TRIP", -2500),
        (date(2026, 10, 1), "Compra no débito - IFD*IFOOD", -4590),
        (date(2026, 10, 3), "Compra no débito - IFD*IFOOD", -3210),
        (date(2026, 10, 4), "Compra no débito - UBER *TRIP", -1800),
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


def test_brl():
    assert brl(123456) == "R$ 1.234,56"
    assert brl(-990) == "-R$ 9,90"


@pytest.mark.parametrize(
    ("period", "month", "expected"),
    [
        ("este_mes", None, (date(2026, 10, 1), TODAY)),
        ("mes_passado", None, (date(2026, 9, 1), date(2026, 9, 30))),
        ("ultimos_3_meses", None, (date(2026, 8, 1), TODAY)),
        ("este_ano", None, (date(2026, 1, 1), TODAY)),
        ("ano_passado", None, (date(2025, 1, 1), date(2025, 12, 31))),
        ("este_mes", "2026-02", (date(2026, 2, 1), date(2026, 2, 28))),  # mês tem prioridade
    ],
)
def test_periodos_calculados_pelo_backend(period, month, expected):
    assert resolve_period(period, month, TODAY) == expected


def test_mes_passado_em_janeiro():
    assert resolve_period("mes_passado", None, date(2027, 1, 15)) == (
        date(2026, 12, 1),
        date(2026, 12, 31),
    )


def test_gastos_ignora_receitas_e_usa_valores_positivos(toolbox):
    result = toolbox.execute("gastos", {"periodo": "este_mes", "limite": 3})
    assert result["total_gasto"] == "R$ 2.016,00"  # o salário não entra
    assert result["quantidade_de_despesas"] == 5
    assert [d["valor"] for d in result["maiores_despesas"]] == [
        "R$ 1.800,00",
        "R$ 120,00",
        "R$ 45,90",
    ]
    assert result["por_categoria"][0] == {"categoria": "Moradia", "total": "R$ 1.800,00"}


def test_gastos_por_estabelecimento(toolbox):
    result = toolbox.execute("gastos", {"periodo": "ultimos_3_meses", "estabelecimento": "uber"})
    assert result["total_gasto"] == "R$ 43,00"
    assert result["filtro"] == "uber"


def test_gastos_por_categoria_sem_acento_e_mes_especifico(toolbox):
    result = toolbox.execute("gastos", {"categoria": "alimentacao", "mes": "2026-09"})
    assert result["total_gasto"] == "R$ 50,00"
    assert result["periodo"] == "setembro de 2026 (01/09/2026 a 30/09/2026)"


def test_periodo_no_campo_do_mes_e_entendido(toolbox):
    # Visto com o qwen2.5:3b real: {"mes": "este_mes", "periodo": "ultimos_3_meses"}.
    junto = toolbox.execute("gastos", {"mes": "este_mes", "periodo": "ultimos_3_meses"})
    assert "erro" not in junto
    assert junto["periodo"] == toolbox.execute("gastos", {"periodo": "ultimos_3_meses"})["periodo"]
    sozinho = toolbox.execute("gastos", {"mes": "mes_passado"})
    assert sozinho["periodo"] == "mês passado (01/09/2026 a 30/09/2026)"


def test_nome_de_loja_como_categoria_vira_busca_por_estabelecimento(toolbox):
    # Visto com o qwen2.5:3b real: {"categoria": "Netflix"}, a ferramenta recusava e o modelo
    # respondia "não foram encontrados gastos".
    result = toolbox.execute("gastos", {"periodo": "ultimos_3_meses", "categoria": "Uber"})
    assert result["total_gasto"] == "R$ 43,00"
    assert result["filtro"] == "Uber"
    assert "não é uma categoria" in result["observacao"]
    # Categoria de verdade não ganha observação.
    assert "observacao" not in toolbox.execute("gastos", {"categoria": "alimentacao"})


def test_nome_que_nao_e_categoria_nem_loja_continua_erro(toolbox):
    assert "não existe" in toolbox.execute("gastos", {"categoria": "Netflix"})["erro"]
    # Com estabelecimento já preenchido, a categoria errada não é reaproveitada.
    result = toolbox.execute("gastos", {"categoria": "Uber", "estabelecimento": "ifood"})
    assert "não existe" in result["erro"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Quanto gastei este mês?", {"periodo": "este_mes"}),
        ("e nesse mês?", {"periodo": "este_mes"}),
        ("Quanto sobrou no mês passado?", {"periodo": "mes_passado"}),
        ("Quanto paguei de Netflix nos últimos 3 meses?", {"periodo": "ultimos_3_meses"}),
        ("gastos dos últimos seis meses", {"periodo": "ultimos_6_meses"}),
        ("quanto recebi este ano", {"periodo": "este_ano"}),
        ("e no ano passado?", {"periodo": "ano_passado"}),
        ("Quanto gastei no mercado em setembro?", {"mes": "2026-09"}),
        ("e em dezembro?", {"mes": "2025-12"}),  # hoje é outubro: dezembro passado
        ("gastos de março de 2025", {"mes": "2025-03"}),
        ("Quanto gastei com Uber?", None),  # sem período: a LLM decide
        ("compare setembro e outubro", None),  # dois períodos: a LLM decide
        ("gastos deste mês e do mês passado", None),
    ],
)
def test_periodo_tirado_da_pergunta(question, expected):
    assert period_from_text(question, TODAY) == expected


def test_periodo_da_pergunta_tem_prioridade_sobre_o_da_llm(db, toolbox):
    # Visto com o qwen2.5:3b real: "últimos 3 meses" com {"periodo": "ultimos_3_meses",
    # "mes": "2026-10"}; como o mês tem prioridade, a resposta saía só de outubro.
    llm_args = {"periodo": "ultimos_3_meses", "mes": "2026-09", "estabelecimento": "uber"}
    sem_pergunta = toolbox.execute("gastos", llm_args)
    assert sem_pergunta["total_gasto"] == "R$ 25,00"

    com_pergunta = Toolbox(db, today=TODAY, question="Quanto gastei de Uber nos últimos 3 meses?")
    result = com_pergunta.execute("gastos", llm_args)
    assert result["total_gasto"] == "R$ 43,00"
    assert result["periodo"] == "últimos 3 meses (01/08/2026 a 20/10/2026)"
    # evolucao_mensal não tem período: os argumentos dela não mudam.
    assert len(com_pergunta.execute("evolucao_mensal", {"meses": 2})["meses"]) == 2


@pytest.mark.parametrize(
    ("question", "args", "expected"),
    [
        # Visto com o qwen2.5:3b real: "por mês" respondido com o total do período.
        ("Quanto gastei por mês nos últimos 3 meses?", {"periodo": "ultimos_3_meses"},
         ("evolucao_mensal", {"meses": 3, "so_despesas": True})),
        ("Gastos mês a mês este ano", {"periodo": "este_ano"},
         ("evolucao_mensal", {"meses": 10, "so_despesas": True})),
        # Com filtro, a evolução mensal não serve (ela não filtra): segue em `gastos`.
        ("Quanto gastei de Uber por mês nos últimos 3 meses?",
         {"periodo": "ultimos_3_meses", "estabelecimento": "uber"}, ("gastos", None)),
        # Um mês só, ou um período que não termina hoje: também segue em `gastos`.
        ("Quanto gastei por mês este mês?", {"periodo": "este_mes"}, ("gastos", None)),
        ("Quanto gastei por mês no ano passado?", {"periodo": "ano_passado"}, ("gastos", None)),
        # Sem "por mês" na pergunta, nada muda.
        ("Quanto gastei nos últimos 3 meses?", {"periodo": "ultimos_3_meses"}, ("gastos", None)),
    ],
)  # fmt: skip
def test_pergunta_por_mes_vira_evolucao_mensal(db, toolbox, question, args, expected):
    routed = Toolbox(db, today=TODAY, question=question).route("gastos", args)
    assert routed[0] == expected[0]
    if expected[1] is not None:
        assert routed[1] == expected[1]


def test_pergunta_por_mes_devolve_os_meses(db, toolbox):
    por_mes = Toolbox(db, today=TODAY, question="Quanto gastei por mês nos últimos 3 meses?")
    result = por_mes.execute("gastos", {"periodo": "ultimos_3_meses"})
    assert [m["despesas"] for m in result["meses"]] == ["R$ 0,00", "R$ 75,00", "R$ 2.016,00"]
    # Visto com o qwen2.5:3b real: com o saldo no resultado, ele o citou como gasto do mês.
    assert all(set(m) == {"mes", "despesas"} for m in result["meses"])
    # Pedida pelo modelo, a evolução mensal continua completa.
    assert "saldo" in toolbox.execute("evolucao_mensal", {"meses": 2})["meses"][0]


def test_resumo_financeiro(toolbox):
    result = toolbox.execute("resumo_financeiro", {"periodo": "este_mes"})
    assert result["receitas"] == "R$ 6.500,00"
    assert result["despesas"] == "R$ 2.016,00"
    assert result["saldo"] == "R$ 4.484,00"
    assert result["situacao"] == "sobrou dinheiro"
    assert result["receitas_por_categoria"] == [{"categoria": "Salário", "total": "R$ 6.500,00"}]


def test_evolucao_mensal(toolbox):
    result = toolbox.execute("evolucao_mensal", {"meses": 2})
    assert result["meses"] == [
        {"mes": "09/2026", "receitas": "R$ 0,00", "despesas": "R$ 75,00", "saldo": "-R$ 75,00"},
        {
            "mes": "10/2026",
            "receitas": "R$ 6.500,00",
            "despesas": "R$ 2.016,00",
            "saldo": "R$ 4.484,00",
        },
    ]


def test_erros_voltam_para_a_llm(toolbox):
    assert "não existe" in toolbox.execute("gastos", {"categoria": "Pets"})["erro"]
    assert "inválidos" in toolbox.execute("gastos", {"periodo": "semana_que_vem"})["erro"]
    assert "desconhecida" in toolbox.execute("apagar_tudo", {})["erro"]
    # Campos vazios e números como texto, que modelos pequenos às vezes mandam, são aceitos.
    assert "erro" not in toolbox.execute(
        "gastos", {"categoria": "", "estabelecimento": None, "limite": "3"}
    )


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
                    {
                        "function": {
                            "name": "gastos",
                            "arguments": {"estabelecimento": "ifood", "periodo": "este_mes"},
                        }
                    }
                ],
            }
        else:
            total = json.loads(body["messages"][-1]["content"])["total_gasto"]
            message = {"role": "assistant", "content": f"Você gastou {total} no iFood."}
        return httpx.Response(200, json={"message": message})

    provider = OllamaProvider(
        "http://ollama", "qwen2.5:3b", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = provider.chat_with_tools(
        "sistema", [{"role": "user", "content": "Quanto gastei no iFood?"}], TOOLS, toolbox.execute
    )

    assert result.answer == "Você gastou R$ 78,00 no iFood."
    assert [c.name for c in result.tool_calls] == ["gastos"]
    assert {t["function"]["name"] for t in requests[0]["tools"]} == {t.name for t in TOOLS}
    assert requests[1]["messages"][-1]["role"] == "tool"


def test_money_values():
    text = "Gastou R$ 1.800,00, depois R$ 2669,12, R$ -45,9 e R$ 7."
    assert money_values(text) == {
        180000: "R$ 1.800,00",
        266912: "R$ 2669,12",
        4590: "R$ -45,9",
        700: "R$ 7",
    }


class _ScriptedLLM:
    """Chama uma ferramenta e devolve uma resposta fixa (para testar a checagem de fatos)."""

    name, model = "fake", "fake"

    def __init__(self, answer: str):
        self.answer = answer

    def chat_with_tools(self, system, messages, tools, execute):
        execute("gastos", {"mes": "2026-10", "limite": 3})
        return ChatResult(answer=self.answer, tool_calls=[ToolCall("gastos", {})])


def test_checagem_de_fatos_aponta_valor_inventado(toolbox):
    # Caso real observado com o qwen2.5:3b: descrição certa, valor inventado.
    llm = _ScriptedLLM("Maiores: R$ 1.800,00 (aluguel), R$ 120,00 (Pix) e R$ 349,65 (Carrefour).")
    answer = ask(toolbox.db, llm, [{"role": "user", "content": "?"}], today=TODAY)
    assert answer.unverified_values == ["R$ 349,65"]


def test_checagem_de_fatos_aceita_formato_diferente(toolbox):
    llm = _ScriptedLLM("Você gastou R$ 2016,00 em outubro.")  # sem separador de milhar
    answer = ask(toolbox.db, llm, [{"role": "user", "content": "?"}], today=TODAY)
    assert answer.unverified_values == []


def test_api_chat(client, fake_llm):
    fake_llm.chat_script = [("evolucao_mensal", {"meses": 3})]
    response = client.post(
        "/api/assistant/chat", json={"messages": [{"role": "user", "content": "Como estou?"}]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "resposta do fake"
    assert body["tool_calls"] == [{"name": "evolucao_mensal", "arguments": {"meses": 3}}]
    assert body["unverified_values"] == []
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
