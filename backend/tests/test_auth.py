"""Login: primeiro acesso, sessão por cookie, HTTP Basic (Power BI) e rotas protegidas."""

import base64

from app.auth import hash_password, verify_password


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _setup(client, username="Isa", password="senha-forte-1"):
    return client.post("/api/auth/setup", json={"username": username, "password": password})


def test_senha_guardada_com_scrypt_e_sal():
    stored = hash_password("minha senha")
    assert stored.startswith("scrypt$") and "minha senha" not in stored
    assert stored != hash_password("minha senha")  # sal aleatório
    assert verify_password("minha senha", stored)
    assert not verify_password("outra senha", stored)
    assert not verify_password("minha senha", "lixo")


def test_rotas_de_dados_exigem_login(anon_client):
    for path in (
        "/api/expenses",
        "/api/transactions",
        "/api/categories",
        "/api/bi/lancamentos.json",
    ):
        assert anon_client.get(path).status_code == 401, path
    assert anon_client.get("/api/health").status_code == 200  # health check continua público


def test_primeiro_acesso_cria_conta_e_ja_entra(anon_client):
    assert anon_client.get("/api/auth/status").json() == {"setup_required": True, "username": None}
    response = _setup(anon_client)
    assert response.status_code == 201
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert anon_client.get("/api/auth/status").json() == {
        "setup_required": False,
        "username": "isa",
    }
    assert anon_client.get("/api/expenses").status_code == 200
    # Depois do primeiro usuário, ninguém mais cria conta sem estar logado.
    anon_client.cookies.clear()
    assert _setup(anon_client, "intruso").status_code == 409


def test_senha_curta_e_recusada(anon_client):
    assert _setup(anon_client, password="curta").status_code == 422
    assert anon_client.get("/api/auth/status").json()["setup_required"] is True


def test_login_logout(anon_client):
    _setup(anon_client)
    anon_client.post("/api/auth/logout")
    assert anon_client.get("/api/expenses").status_code == 401

    wrong = anon_client.post("/api/auth/login", json={"username": "isa", "password": "errada123"})
    assert wrong.status_code == 401
    assert "www-authenticate" not in wrong.headers  # não abre a janela de senha do navegador
    ok = anon_client.post(
        "/api/auth/login", json={"username": " ISA ", "password": "senha-forte-1"}
    )
    assert ok.status_code == 200
    assert anon_client.get("/api/expenses").status_code == 200


def test_power_bi_entra_com_http_basic(anon_client):
    _setup(anon_client)
    anon_client.cookies.clear()
    # Sem credencial, a rota de BI pede Basic (o Power BI responde com usuário e senha).
    challenge = anon_client.get("/api/bi/lancamentos.json")
    assert challenge.status_code == 401
    assert challenge.headers["www-authenticate"].startswith("Basic")
    assert anon_client.get("/api/expenses").headers.get("www-authenticate") is None

    ok = anon_client.get("/api/bi/lancamentos.json", headers=_basic("isa", "senha-forte-1"))
    assert ok.status_code == 200
    wrong = anon_client.get("/api/bi/lancamentos.json", headers=_basic("isa", "errada123"))
    assert wrong.status_code == 401


def test_trocar_senha_derruba_as_outras_sessoes(anon_client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    _setup(anon_client)
    with TestClient(app) as other:  # outro navegador, logado com a mesma conta
        other.post("/api/auth/login", json={"username": "isa", "password": "senha-forte-1"})
        assert other.get("/api/expenses").status_code == 200

        bad = anon_client.post(
            "/api/auth/password", json={"current_password": "x", "new_password": "nova-senha-2"}
        )
        assert bad.status_code == 403
        changed = anon_client.post(
            "/api/auth/password",
            json={"current_password": "senha-forte-1", "new_password": "nova-senha-2"},
        )
        assert changed.status_code == 204
        assert anon_client.get("/api/expenses").status_code == 200  # quem trocou continua
        assert other.get("/api/expenses").status_code == 401  # o outro navegador caiu


def test_usuario_logado_cadastra_outra_pessoa(anon_client):
    _setup(anon_client)
    created = anon_client.post(
        "/api/auth/users", json={"username": "Ana", "password": "senha-da-ana"}
    )
    assert created.status_code == 201
    duplicate = anon_client.post(
        "/api/auth/users", json={"username": "ana", "password": "outra-senha"}
    )
    assert duplicate.status_code == 422
