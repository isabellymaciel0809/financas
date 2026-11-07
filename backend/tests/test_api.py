NUBANK_CSV = (
    "Data,Valor,Identificador,Descrição\n"
    "01/10/2026,-45.90,a,Compra no débito - IFD*IFOOD\n"
    "02/10/2026,-30.00,b,Compra no débito - SumUp *BARBEARIA DO ZE\n"
    "03/10/2026,-120.00,c,Pix enviado - Maria Oliveira\n"
    "05/10/2026,6500.00,d,Transferência recebida - Salário ACME\n"
    "10/09/2026,-50.00,e,Compra no débito - SumUp *BARBEARIA DO ZE\n"
).encode()


def _upload(client, content=NUBANK_CSV, name="extrato.csv"):
    return client.post("/api/imports", files={"file": (name, content, "text/csv")})


def _category_id(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def test_health(client):
    body = client.get("/api/health").json()
    assert body == {
        "status": "ok",
        "llm_provider": "fake",
        "llm_model": "fake-1",
        "llm_available": True,
    }


def test_importacao_e_deduplicacao(client, fake_llm):
    fake_llm.answers = {"maria": ("Transferências", 0.8)}
    first = _upload(client).json()
    assert first["imported"] == 5
    assert first["categorization"] == {"memory": 0, "rule": 2, "llm": 1, "none": 2}

    second = _upload(client).json()
    assert second["imported"] == 0
    assert second["duplicates"] == 5


def test_arquivo_invalido_retorna_422(client):
    response = _upload(client, b"isso nao e um extrato", "x.csv")
    assert response.status_code == 422


def test_correcao_aprende_e_aplica_em_semelhantes(client):
    _upload(client)
    pending = client.get("/api/transactions", params={"uncategorized": True}).json()
    barbearia = next(t for t in pending["items"] if "BARBEARIA" in t["description"])
    lazer = _category_id(client, "Lazer")

    result = client.patch(f"/api/transactions/{barbearia['id']}", json={"category_id": lazer})
    assert result.status_code == 200
    assert result.json()["transaction"]["categorized_by"] == "manual"
    assert result.json()["similar_updated"] == 1  # a outra visita à barbearia

    # Próxima importação do mesmo estabelecimento usa a memória, sem chamar regra/LLM.
    new_csv = b"Data,Valor,Descricao\n01/11/2026,-35.00,SumUp *BARBEARIA DO ZE\n"
    imported = _upload(client, new_csv, "novembro.csv").json()
    assert imported["categorization"]["memory"] == 1


def test_recategorizar_pendentes(client, fake_llm):
    _upload(client)
    fake_llm.answers = {"maria": ("Transferências", 0.9), "barbearia": ("Lazer", 0.9)}
    body = client.post("/api/transactions/categorize").json()
    assert body["processed"] == 3
    assert body["categorization"]["llm"] == 3


def test_criar_transacao_manual(client):
    response = client.post(
        "/api/transactions",
        json={"date": "2026-10-15", "description": "Uber para o trabalho", "amount_cents": -2500},
    )
    assert response.status_code == 201
    assert response.json()["category"]["name"] == "Transporte"


def test_dashboard(client):
    _upload(client)
    summary = client.get("/api/dashboard/summary", params={"month": "2026-10"}).json()
    assert summary["income_cents"] == 650000
    assert summary["expense_cents"] == 4590 + 3000 + 12000
    assert summary["balance_cents"] == 650000 - 19590
    assert summary["transaction_count"] == 4
    assert summary["monthly"][-2:] == [
        {"month": "2026-09", "income_cents": 0, "expense_cents": 5000},
        {"month": "2026-10", "income_cents": 650000, "expense_cents": 19590},
    ]
    names = [c["name"] for c in summary["expenses_by_category"]]
    assert "Alimentação" in names and "Sem categoria" in names


def test_dashboard_usa_ultimo_mes_com_dados(client):
    _upload(client)
    assert client.get("/api/dashboard/summary").json()["month"] == "2026-10"


def test_demo(client):
    body = client.post("/api/demo").json()
    assert body["imported"] > 50
    assert body["categorization"]["rule"] > body["categorization"]["none"]
