"""Garante que o script de avaliação roda e que as regras não regridem."""

from datetime import date

from app.config import Settings
from evals.run_eval import EVAL_DIR, load_cases, report, run, summarize


def test_avaliacao_baseline_de_regras():
    cases = load_cases(EVAL_DIR / "dataset.csv")
    predictions, meta = run(cases, Settings(llm_provider="none"))
    summary = summarize(predictions)

    assert summary["total"] == len(cases) >= 140
    # Quando uma regra se aplica, ela precisa estar certa: erro de regra é bug.
    assert summary["rules"]["accuracy"] == 1.0
    assert summary["rules"]["coverage"] >= 0.65
    assert "Acerto de ponta a ponta" in report(summary, predictions, meta)


def test_conjunto_de_teste_e_separado_do_de_desenvolvimento():
    """O conjunto de teste só mede algo se não tiver nenhum estabelecimento do outro."""
    from app.services.text import merchant_key

    dev = {merchant_key(c.description) for c in load_cases(EVAL_DIR / "dataset.csv")}
    test = load_cases(EVAL_DIR / "teste.csv")
    assert len(test) >= 50
    assert [c.description for c in test if merchant_key(c.description) in dev] == []
    predictions, _ = run(test, Settings(llm_provider="none"))
    assert summarize(predictions)["rules"]["accuracy"] == 1.0  # regra errada é bug


# --- Avaliação do assistente (evals/run_assistant_eval.py) -----------------------------------


class _Roteiro:
    """Provedor que chama a ferramenta pedida e responde com o texto montado pelo teste."""

    name, model = "roteiro", "v1"

    def __init__(self, chamada, resposta):
        self.chamada, self.resposta = chamada, resposta

    def chat_with_tools(self, system, messages, tools, execute):
        from app.services.categorizer.llm import ChatResult, ToolCall

        calls = []
        if self.chamada:
            result = execute(*self.chamada)
            calls.append(ToolCall(*self.chamada))
            return ChatResult(self.resposta(result), calls)
        return ChatResult(self.resposta({}), calls)


def _avaliar(pergunta, chamada, resposta):
    from evals.run_assistant_eval import demo_db, evaluate

    return evaluate(demo_db(), _Roteiro(chamada, resposta), pergunta)


def _pergunta(**kw):
    from evals.run_assistant_eval import Question

    base = {
        "pergunta": "Quanto gastei com Uber nos últimos 3 meses?",
        "chamada": {
            "ferramenta": "gastos",
            "argumentos": {"periodo": "ultimos_3_meses", "estabelecimento": "uber"},
        },
        "valor": "total_gasto",
        "proibido": ["último mês"],
    }
    return Question(**(base | kw))


UBER_3M = ("gastos", {"periodo": "ultimos_3_meses", "estabelecimento": "uber"})


def test_avaliacao_do_assistente_aceita_resposta_certa():
    r = _avaliar(_pergunta(), UBER_3M, lambda res: f"Nos últimos 3 meses: {res['total_gasto']}.")
    assert r.ok, r


def test_avaliacao_do_assistente_pega_consulta_errada():
    errado = ("gastos", {"periodo": "ultimos_3_meses", "estabelecimento": "ifood"})
    r = _avaliar(_pergunta(), errado, lambda res: f"Você gastou {res['total_gasto']}.")
    assert not r.consulta_ok and not r.valor_ok


def test_avaliacao_do_assistente_pega_periodo_errado_quando_a_pergunta_nao_diz():
    sem_periodo = _pergunta(
        pergunta="Quanto gastei com Uber?",
        chamada={"ferramenta": "gastos", "argumentos": {"periodo": "ultimos_3_meses",
                                                         "estabelecimento": "uber"}},
    )  # fmt: skip
    errado = ("gastos", {"periodo": "este_mes", "estabelecimento": "uber"})
    r = _avaliar(sem_periodo, errado, lambda res: f"Você gastou {res['total_gasto']}.")
    assert not r.consulta_ok and not r.valor_ok


def test_avaliacao_do_assistente_conta_a_correcao_de_periodo_do_backend():
    # A pergunta diz "últimos 3 meses": o app corrige o período errado do modelo, e a avaliação
    # refaz a consulta como o app fez.
    errado = ("gastos", {"periodo": "este_mes", "mes": "2026-10", "estabelecimento": "uber"})
    r = _avaliar(_pergunta(), errado, lambda res: f"Nos últimos 3 meses: {res['total_gasto']}.")
    assert r.ok, r


def test_avaliacao_do_assistente_pega_frase_errada_e_valor_inventado():
    r = _avaliar(_pergunta(), UBER_3M, lambda res: "No último mês, você gastou R$ 999,99.")
    assert r.consulta_ok
    assert not r.valor_ok and not r.fatos_ok and not r.frases_ok


def test_pergunta_fora_do_escopo_nao_pode_citar_valores():
    fora = _pergunta(pergunta="Vai chover amanhã?", chamada=None, valor=None, proibido=[])
    assert _avaliar(fora, None, lambda res: "Só respondo sobre suas finanças.").ok
    assert not _avaliar(fora, None, lambda res: "Amanhã você gasta R$ 10,00.").ok


def test_perguntas_do_assistente_tem_valor_esperado():
    from evals.run_assistant_eval import EVAL_DIR, Toolbox, demo_db, load_questions, lookup

    toolbox = Toolbox(demo_db(), today=date(2026, 11, 11))
    for q in load_questions(EVAL_DIR / "assistente.json"):
        if q.chamada:
            result = toolbox.execute(q.chamada["ferramenta"], q.chamada["argumentos"])
            assert "erro" not in result, (q.pergunta, result)
            assert lookup(result, q.valor), q.pergunta
