"""Alertas de gastos fora do padrão no dashboard."""


def _extrato(*rows: tuple[str, float, str]) -> bytes:
    lines = ["Data,Valor,Identificador,Descrição"]
    lines += [f"{d},{v:.2f},id{i},{desc}" for i, (d, v, desc) in enumerate(rows)]
    return ("\n".join(lines) + "\n").encode()


def _alerts(client, csv: bytes, month: str = "2026-10"):
    client.post("/api/imports", files={"file": ("extrato.csv", csv, "text/csv")})
    summary = client.get("/api/dashboard/summary", params={"month": month}).json()
    return {a["name"]: a for a in summary["alerts"]}


IFOOD = "Compra no débito - IFD*IFOOD"
UBER = "Compra no débito - UBER *TRIP"


def test_gasto_muito_acima_da_media_vira_alerta(client):
    alerts = _alerts(
        client,
        _extrato(
            ("10/08/2026", -100.00, IFOOD),
            ("10/09/2026", -120.00, IFOOD),
            ("10/10/2026", -180.00, IFOOD),
            ("20/10/2026", -120.00, IFOOD),
        ),
    )
    assert alerts["Alimentação"]["current_cents"] == 300_00
    assert alerts["Alimentação"]["baseline_cents"] == 110_00  # média de agosto e setembro
    assert alerts["Alimentação"]["baseline_months"] == 2


def test_diferenca_pequena_em_reais_nao_e_alerta(client):
    # 75% acima da média, mas só R$ 30 a mais: não vale um alerta.
    alerts = _alerts(
        client,
        _extrato(
            ("10/08/2026", -40.00, UBER),
            ("10/09/2026", -40.00, UBER),
            ("10/10/2026", -70.00, UBER),
        ),
    )
    assert alerts == {}


def test_gasto_dentro_do_normal_nao_e_alerta(client):
    alerts = _alerts(
        client,
        _extrato(
            ("10/08/2026", -200.00, IFOOD),
            ("10/09/2026", -260.00, IFOOD),
            ("10/10/2026", -250.00, IFOOD),
        ),
    )
    assert alerts == {}


def test_categoria_nova_com_valor_alto_vira_alerta(client):
    alerts = _alerts(
        client,
        _extrato(
            ("10/09/2026", -50.00, IFOOD),
            ("10/10/2026", -150.00, UBER),
        ),
    )
    assert alerts["Transporte"]["baseline_cents"] == 0
    assert alerts["Transporte"]["current_cents"] == 150_00


def test_meses_sem_nenhuma_transacao_nao_entram_na_media(client):
    # Começou a usar em setembro: a média é só de setembro, não de 3 meses com dois zerados.
    alerts = _alerts(
        client,
        _extrato(
            ("10/09/2026", -100.00, IFOOD),
            ("10/10/2026", -130.00, IFOOD),
        ),
    )
    assert alerts == {}  # 30% acima de R$ 100, e não 290% acima de R$ 33


def test_primeiro_mes_nao_tem_alertas(client):
    alerts = _alerts(client, _extrato(("10/10/2026", -900.00, IFOOD)))
    assert alerts == {}


def test_receitas_nao_viram_alerta(client):
    alerts = _alerts(
        client,
        _extrato(
            ("10/09/2026", 100.00, "Pix recebido - Cliente"),
            ("10/10/2026", 5000.00, "Pix recebido - Cliente"),
        ),
    )
    assert alerts == {}


def test_dados_de_exemplo_mostram_um_alerta_no_mes_atual(client):
    client.post("/api/demo")
    alerts = client.get("/api/dashboard/summary").json()["alerts"]
    assert [a["name"] for a in alerts] == ["Compras"]
