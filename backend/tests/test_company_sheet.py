"""Integração com a planilha que a empresa já usa: importar o histórico e atualizar o arquivo."""

import io
from datetime import datetime

from openpyxl import Workbook, load_workbook

HEADERS = ["Data", "Mês", "Cliente/Fornecedor", "Proposta", "Descrição", "Tipo", " Valor (R$)"]


def company_workbook() -> bytes:
    """Planilha como a de uma empresa real: título, formatos variados, total e outra aba."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Controle"
    ws["A1"] = "CONTROLE FINANCEIRO 2026"
    ws.append([])
    ws.append(HEADERS)  # cabeçalho na linha 3 (com o espaço antes de "Valor", como veio)
    rows = [
        [
            datetime(2026, 10, 1),
            datetime(2026, 10, 1),
            "Frigelar",
            "P-100",
            "Tubo de cobre 1/2",
            "Custo",
            327.6,
        ],
        ["05/10/2026", "out/26", "Vivo", None, "Internet", "Despesas", "R$ 119,99"],
        [datetime(2026, 10, 8), None, "Posto Shell", "P-100", "Combustível", "Custo", 150],
        [
            datetime(2026, 10, 8),
            None,
            "Posto Shell",
            "P-100",
            "Combustível",
            "Custo",
            150,
        ],  # repetida
        [datetime(2026, 10, 20), None, "Mercado Bom Preço", "P-100", "Instalação", "Receita", 2500],
    ]
    for row in rows:
        ws.append(row)
    for r in range(4, 9):
        ws.cell(r, 1).number_format = "DD/MM/YYYY"
        ws.cell(r, 7).number_format = "#,##0.00"
    ws.append([None, None, None, None, "TOTAL", None, "=SUM(G4:G8)"])  # linha 9
    wb.create_sheet("Resumo")["A1"] = "Aba da empresa que não pode sumir"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _import(client, content: bytes, name: str = "controle.xlsx"):
    return client.post("/api/expenses/spreadsheet/import", files={"file": (name, content)})


def test_importa_historico_da_planilha(client):
    response = _import(client, company_workbook())
    assert response.status_code == 200
    assert response.json() == {
        "sheet": "Controle",
        "imported": 5,
        "duplicates": 0,
        "already_in_system": 0,
        "skipped": 1,  # a linha de TOTAL
        "skipped_rows": [9],
    }
    expenses = client.get("/api/expenses").json()
    assert all(e["status"] == "confirmed" and e["from_spreadsheet"] for e in expenses)

    report = client.get("/api/expenses/items", params={"proposal": "P-100"}).json()
    by_type = {g["name"]: g["total_cents"] for g in report["by_type"]}
    assert by_type == {"Receita": 250000, "Custo": 62760}  # 327,60 + 150 + 150

    internet = client.get("/api/expenses/items", params={"search": "internet"}).json()["items"][0]
    assert internet["total_cents"] == 11999  # "R$ 119,99" em texto
    assert internet["issue_date"] == "2026-10-05"  # "05/10/2026" em texto
    assert internet["category"]["name"] == "Contas e serviços"  # regra "internet"


def test_reimportar_nao_duplica(client):
    _import(client, company_workbook())
    again = _import(client, company_workbook()).json()
    assert again["imported"] == 0
    assert again["duplicates"] == 5  # inclusive as duas linhas idênticas de combustível
    assert len(client.get("/api/expenses").json()) == 5


def test_planilha_sem_as_colunas(client):
    wb = Workbook()
    wb.active.append(["Nome", "Idade"])
    buffer = io.BytesIO()
    wb.save(buffer)
    response = _import(client, buffer.getvalue())
    assert response.status_code == 422
    assert "Data, Descrição e Valor" in response.json()["detail"]
    assert _import(client, b"x", "planilha.csv").status_code == 415


def test_atualiza_a_planilha_da_empresa_sem_repetir_linhas(client):
    _import(client, company_workbook())  # o histórico já está no sistema
    # Lançamentos novos do sistema: um que já foi digitado na planilha e outro que não.
    for description, cents in [("Internet", 11999), ("Aluguel do galpão", 250000)]:
        client.post(
            "/api/expenses",
            json={
                "issue_date": "2026-10-05" if description == "Internet" else "2026-10-25",
                "description": description,
                "supplier_name": "Imobiliária Lar" if description != "Internet" else "Vivo",
                "items": [{"description": description, "total_cents": cents}],
            },
        )

    response = client.post(
        "/api/expenses/spreadsheet/update",
        files={"file": ("controle.xlsx", company_workbook())},
        data={"month": "2026-10"},
    )
    assert response.status_code == 200
    assert response.headers["x-rows-added"] == "1"
    assert response.headers["x-rows-already-in-sheet"] == "1"  # "Internet" já estava lá
    assert "controle-atualizada.xlsx" in response.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["Controle", "Resumo"]  # a outra aba continua lá
    assert wb["Resumo"]["A1"].value == "Aba da empresa que não pode sumir"
    ws = wb["Controle"]
    new_row = [c.value for c in ws[9]]  # entrou logo depois do último lançamento...
    assert new_row[0] == datetime(2026, 10, 25)
    assert new_row[2:] == ["Imobiliária Lar", None, "Aluguel do galpão", "Despesas", 2500.0]
    assert ws.cell(9, 1).number_format == "DD/MM/YYYY"  # formato copiado da linha de cima
    # ...e o TOTAL desceu uma linha, com a soma estendida para incluir a linha nova.
    assert [c.value for c in ws[10]][4:] == ["TOTAL", None, "=SUM(G4:G9)"]


def test_importar_o_proprio_excel_exportado_nao_duplica(client):
    """Bug real: a planilha enviada era o Excel exportado pelo sistema, com um lançamento
    manual que já existia, e ele foi importado de novo como duplicata."""
    others = next(c["id"] for c in client.get("/api/categories").json() if c["name"] == "Outros")
    manual = client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-05",
            "description": "Pagamento",
            "items": [{"description": "Pagamento", "total_cents": 160000, "category_id": others}],
        },
    ).json()
    assert manual["status"] == "confirmed"  # só confirmados vão para a exportação
    exported = client.get("/api/expenses/export.xlsx", params={"month": "2026-11"}).content

    result = _import(client, exported).json()
    assert result["imported"] == 0
    assert result["already_in_system"] == 1
    assert len(client.get("/api/expenses").json()) == 1
