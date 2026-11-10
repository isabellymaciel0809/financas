"""Cada usuário usa o organizador sozinho: um não vê, não altera e não apaga nada do outro.

Os testes usam logins de verdade (cookies), sem atalhos: é o mesmo caminho do navegador.
"""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Transaction
from tests.test_fiscal import make_key, make_nfe_xml


def _login(client: TestClient, username: str, password: str = "senha-forte-1") -> TestClient:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def two_users(anon_client):
    """Ana cria a primeira conta e cadastra o Beto; cada um num navegador próprio."""
    ana = anon_client
    ana.post("/api/auth/setup", json={"username": "ana", "password": "senha-forte-1"})
    ana.post("/api/auth/users", json={"username": "beto", "password": "senha-forte-1"})
    with TestClient(app) as beto:
        yield ana, _login(beto, "beto")


def _fill(client: TestClient, label: str) -> dict:
    """Usa o organizador como uma pessoa usaria: extrato, nota, lançamento, funcionário."""
    client.post("/api/demo")
    employee = client.post("/api/employees", json={"name": f"Funcionário {label}"}).json()
    expense = client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-05",
            "description": f"Compra {label}",
            "employee_id": employee["id"],
            "items": [{"description": f"Item {label}", "total_cents": 1000}],
        },
    ).json()
    category = client.post("/api/categories", json={"name": f"Categoria {label}"}).json()
    return {"employee": employee, "expense": expense, "category": category}


def test_cada_um_ve_so_o_que_e_seu(two_users):
    ana, beto = two_users
    mine = _fill(ana, "da Ana")
    _fill(beto, "do Beto")

    expenses = [e["description"] for e in ana.get("/api/expenses").json()]
    assert expenses == ["Compra da Ana"]
    assert [e["name"] for e in ana.get("/api/employees").json()] == ["Funcionário da Ana"]
    items = ana.get("/api/expenses/items").json()["items"]
    assert [i["description"] for i in items] == ["Item da Ana"]
    bi = ana.get("/api/bi/lancamentos.json").json()
    assert [r["descricao"] for r in bi] == ["Item da Ana"]

    categories = {c["name"] for c in ana.get("/api/categories").json()}
    assert "Categoria da Ana" in categories and "Categoria do Beto" not in categories
    assert "Mercado" in categories  # as padrão valem para todos

    # O mesmo extrato de exemplo foi importado pelos dois: cada um tem o seu (sem "duplicata").
    ana_tx = ana.get("/api/transactions").json()["total"]
    assert ana_tx == beto.get("/api/transactions").json()["total"] > 0
    summary = ana.get("/api/dashboard/summary").json()
    assert summary["transaction_count"] <= ana_tx

    assert mine["expense"]["employee"]["name"] == "Funcionário da Ana"


def test_nao_acessa_nem_altera_o_do_outro_pelo_id(two_users):
    ana, beto = two_users
    mine = _fill(ana, "da Ana")
    expense_id, employee_id = mine["expense"]["id"], mine["employee"]["id"]
    transaction_id = ana.get("/api/transactions").json()["items"][0]["id"]

    assert beto.get(f"/api/expenses/{expense_id}").status_code == 404
    assert beto.patch(f"/api/expenses/{expense_id}", json={"description": "x"}).status_code == 404
    assert beto.delete(f"/api/expenses/{expense_id}").status_code == 404
    assert beto.put(f"/api/employees/{employee_id}", json={"name": "x"}).status_code == 404
    assert beto.delete(f"/api/transactions/{transaction_id}").status_code == 404
    # Nem usando a categoria privada da Ana num lançamento dele.
    other = beto.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-05",
            "description": "Teste",
            "items": [
                {"description": "x", "total_cents": 1, "category_id": mine["category"]["id"]}
            ],
        },
    )
    assert other.status_code == 422

    # Tudo da Ana continua intacto.
    assert ana.get(f"/api/expenses/{expense_id}").json()["description"] == "Compra da Ana"
    assert ana.delete(f"/api/transactions/{transaction_id}").status_code == 204


def test_mesma_nota_para_duas_pessoas_nao_e_duplicata(two_users):
    ana, beto = two_users
    xml = make_nfe_xml(key=make_key(number=4321))
    for client in (ana, beto):
        response = client.post("/api/expenses/upload", files=[("files", ("nota.xml", xml))])
        expense_id = response.json()[0]["id"]
        # A fila em segundo plano processa em nome do dono do arquivo: lida, e não duplicata.
        detail = client.get(f"/api/expenses/{expense_id}").json()
        assert detail["supplier"]["name"] == "FRIGELAR"
        assert detail["status"] == "needs_review"  # o desconto do XML de teste gera um aviso
    # Mas a mesma nota duas vezes para a mesma pessoa continua sendo duplicata.
    again = ana.post("/api/expenses/upload", files=[("files", ("nota.xml", xml))]).json()[0]
    assert ana.get(f"/api/expenses/{again['id']}").json()["status"] == "duplicate"


def test_correcao_de_categoria_vira_memoria_so_de_quem_corrigiu(two_users, db):
    ana, beto = two_users
    for client in (ana, beto):
        client.post("/api/demo")
    lazer = next(c["id"] for c in ana.get("/api/categories").json() if c["name"] == "Lazer")
    target = next(
        t for t in ana.get("/api/transactions").json()["items"] if "IFOOD" in t["description"]
    )
    ana.patch(f"/api/transactions/{target['id']}", json={"category_id": lazer})

    def ifood_categories(client):
        items = client.get("/api/transactions", params={"search": "ifood"}).json()["items"]
        return {t["category"]["name"] for t in items}

    assert ifood_categories(ana) == {"Lazer"}
    assert ifood_categories(beto) == {"Alimentação"}  # a correção da Ana não mexe no Beto


def test_power_bi_de_cada_um(two_users):
    ana, beto = two_users
    _fill(ana, "da Ana")
    _fill(beto, "do Beto")
    token = base64.b64encode(b"beto:senha-forte-1").decode()
    with TestClient(app) as power_bi:  # sem cookie, só Basic
        rows = power_bi.get(
            "/api/bi/lancamentos.json", headers={"Authorization": f"Basic {token}"}
        ).json()
    assert [r["descricao"] for r in rows] == ["Item do Beto"]


def test_primeira_conta_fica_com_os_dados_de_antes_do_login(anon_client, db):
    """Quem já usava o app antes do login (dados sem dono) não perde nada ao criar a conta."""
    db.add(
        Transaction(
            date=__import__("datetime").date(2026, 10, 1),
            description="Antes do login",
            amount_cents=-100,
            merchant_key="antes do login",
            fingerprint="x",
        )
    )
    db.commit()
    anon_client.post("/api/auth/setup", json={"username": "ana", "password": "senha-forte-1"})
    items = anon_client.get("/api/transactions").json()["items"]
    assert [t["description"] for t in items] == ["Antes do login"]
    db.expire_all()
    assert db.scalar(select(Transaction.user_id)) is not None
