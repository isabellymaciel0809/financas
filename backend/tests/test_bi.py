"""Fonte de dados para o Power BI."""


def _seed(client):
    receita = next(
        c["id"] for c in client.get("/api/categories").json() if c["name"] == "Receita de serviços"
    )
    client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-10-20",
            "description": "Instalação 9000 Btus",
            "supplier_name": "Gabriel Piccinalli",
            "proposal": "003-2026",
            "entry_type": "Receita",
            "items": [
                {
                    "description": "Instalação 9000 Btus",
                    "total_cents": 120000,
                    "category_id": receita,
                }
            ],
        },
    )
    client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-10-21",
            "description": "Kit instalação",
            "supplier_name": "Frigelar",
            "proposal": "003-2026",
            "items": [{"description": "Tubo de cobre 1/2", "total_cents": 27198}],
        },
    )


def test_json_para_power_bi(client):
    _seed(client)
    rows = client.get("/api/bi/lancamentos.json").json()
    by_type = {r["tipo"]: r for r in rows}
    receita, custo = by_type["Receita"], by_type["Custo"]  # com proposta, o padrão é Custo

    assert (receita["data"], receita["ano"], receita["mes"]) == ("2026-10-20", 2026, 10)
    assert (receita["valor"], receita["valor_com_sinal"], receita["sentido"]) == (
        1200.0,
        1200.0,
        "Entrada",
    )
    assert (custo["valor"], custo["valor_com_sinal"], custo["sentido"]) == (
        271.98,
        -271.98,
        "Saída",
    )
    assert custo["categoria"] == "Materiais e manutenção"
    assert custo["proposta"] == "003-2026"
    assert custo["status"] == "Confirmado"
    # Resultado da proposta direto do BI: soma do valor com sinal.
    assert round(sum(r["valor_com_sinal"] for r in rows), 2) == 928.02


def test_csv_no_padrao_brasileiro(client):
    _seed(client)
    response = client.get("/api/bi/lancamentos.csv")
    text = response.content.decode("utf-8-sig")
    header, *lines = text.strip().splitlines()
    assert header.startswith("id_lancamento;id_item;data;ano;mes;cliente_fornecedor")
    assert any(";1200,00;1200,00;Entrada;" in line for line in lines)
    assert any("Frigelar" in line and ";271,98;-271,98;Saída;" in line for line in lines)
