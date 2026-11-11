"""Lançamento por texto: leitor por padrões, LLM como segunda tentativa e a prévia na API."""

from datetime import date, timedelta

import pytest

from app.services.quick_entry import NotUnderstood, parse_with_rules

HOJE = date(2026, 11, 11)  # quarta-feira


@pytest.mark.parametrize(
    ("texto", "data", "descricao", "centavos"),
    [
        ("gastei 45 no mercado ontem", date(2026, 11, 10), "Mercado", -4500),
        ("paguei R$ 120,50 de luz", HOJE, "Luz", -12050),
        ("recebi 1.200 de freela dia 5", date(2026, 11, 5), "Freela", 120000),
        ("uber 23,90 anteontem", date(2026, 11, 9), "Uber", -2390),
        ("almoço 32 reais na sexta", date(2026, 11, 6), "Almoço", -3200),
        ("gastei 80 na farmácia em 25/12", date(2025, 12, 25), "Farmácia", -8000),
        ("1,5 mil de aluguel", HOJE, "Aluguel", -150000),
        ("dia 28 paguei 50 de gás", date(2026, 10, 28), "Gás", -5000),
        ("Ganhei 300 vendendo a bicicleta hoje", HOJE, "Vendendo a bicicleta", 30000),
        ("ifood 42.90", HOJE, "Ifood", -4290),
    ],
)
def test_leitor_por_padroes(texto, data, descricao, centavos):
    entry = parse_with_rules(texto, HOJE)
    assert entry is not None
    assert (entry.date, entry.description, entry.amount_cents) == (data, descricao, centavos)
    assert entry.understood_by == "regras"


@pytest.mark.parametrize(
    "texto",
    [
        "comprei 2 pizzas por 80",  # dois números: qual é o valor?
        "gastei cinquenta no mercado",  # valor por extenso
        "gastei 45",  # sem descrição
    ],
)
def test_leitor_nao_chuta_quando_nao_tem_certeza(texto):
    assert parse_with_rules(texto, HOJE) is None


def test_data_que_nao_existe():
    with pytest.raises(NotUnderstood, match="31/02"):
        parse_with_rules("gastei 10 em 31/02", HOJE)


# --- API: prévia, LLM e confirmação --------------------------------------------------------


def _preview(client, texto):
    return client.post("/api/transactions/parse", json={"texto": texto})


def test_previa_nao_salva_nada_e_sugere_categoria(client):
    body = _preview(client, "gastei 45 no mercado ontem").json()
    assert body["description"] == "Mercado"
    assert body["amount_cents"] == -4500
    assert body["date"] == str(date.today() - timedelta(days=1))
    assert body["understood_by"] == "regras"
    assert (body["category"]["name"], body["category_source"]) == ("Mercado", "rule")
    assert client.get("/api/transactions").json()["total"] == 0


def test_confirmar_a_previa_categoriza_pela_cascata(client):
    body = _preview(client, "gastei 45 no mercado ontem").json()
    created = client.post(
        "/api/transactions",
        json={k: body[k] for k in ("date", "description", "amount_cents")},
    ).json()
    assert created["category"]["name"] == "Mercado"
    assert created["categorized_by"] == "rule"  # não "manual": foi a regra que decidiu


def test_sugestao_usa_a_memoria_das_correcoes(client):
    tx = client.post(
        "/api/transactions",
        json={"date": "2026-11-01", "description": "Padaria do Zé", "amount_cents": -1200},
    ).json()
    food = next(c["id"] for c in client.get("/api/categories").json() if c["name"] == "Alimentação")
    client.patch(f"/api/transactions/{tx['id']}", json={"category_id": food})

    body = _preview(client, "gastei 15 na padaria do zé").json()
    assert (body["category"]["name"], body["category_source"]) == ("Alimentação", "memory")


def test_llm_entende_valor_por_extenso(client, fake_llm):
    fake_llm.extraction = {"valor": 52.9, "descricao": "Gastei no mercado"}
    body = _preview(client, "gastei cinquenta e dois e noventa no mercado").json()
    assert (body["amount_cents"], body["description"]) == (-5290, "Mercado")  # sem o verbo
    assert body["understood_by"] == "ia"
    assert body["warnings"] == ["O valor foi escrito por extenso: confira."]


def test_data_e_tipo_sao_do_backend_e_a_descricao_so_tem_palavras_da_frase(client, fake_llm):
    # Respostas reais do qwen2.5:3b: inventou "Vendendo" e marcou o gasto como receita.
    fake_llm.extraction = {"valor": 30, "descricao": "Vendendo trinta contos no bar"}
    body = _preview(client, "torrei trinta conto no bar sexta").json()
    assert (body["amount_cents"], body["description"]) == (-3000, "Bar")
    sexta = date.today() - timedelta(days=(date.today().weekday() - 4) % 7)
    assert body["date"] == str(sexta)


def test_receita_por_extenso(client, fake_llm):
    fake_llm.extraction = {"valor": 1200, "descricao": "Recebido do freela"}
    body = _preview(client, "recebi mil e duzentos do freela").json()
    assert (body["amount_cents"], body["description"]) == (120000, "Freela")


def test_llm_escolhe_o_valor_entre_os_numeros_do_texto(client, fake_llm):
    fake_llm.extraction = {"valor": 80, "descricao": "pizzas"}
    body = _preview(client, "comprei 2 pizzas por 80").json()
    assert (body["amount_cents"], body["description"]) == (-8000, "Pizzas")


def test_valor_inventado_pela_llm_e_recusado(client, fake_llm):
    # O texto fala em 2 e 80; 160 (2 × 80) não está escrito: a LLM calculou, e não leu.
    fake_llm.extraction = {"valor": 160, "descricao": "pizza"}
    response = _preview(client, "comprei 2 pizzas por 80")
    assert response.status_code == 422
    assert "valor" in response.json()["detail"]


def test_outros_numeros_no_texto_geram_aviso(client):
    body = _preview(client, "paguei 3 cafés de 7 reais").json()
    assert body["amount_cents"] == -700
    assert body["warnings"] == ["Havia outros números no texto: confira o valor."]


def test_data_futura_e_recusada(client):
    response = _preview(client, "gastei 30 no cinema em 25/12/2099")
    assert response.status_code == 422
    assert "ainda não chegou" in response.json()["detail"]


def test_sem_llm_pede_o_valor_em_numeros(client, fake_llm):
    fake_llm.fail = True
    response = _preview(client, "gastei cinquenta no mercado")
    assert response.status_code == 422
    assert "valor em números" in response.json()["detail"]
