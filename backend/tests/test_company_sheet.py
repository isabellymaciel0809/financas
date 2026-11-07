"""Integração com a planilha que a empresa já usa: importar o histórico e atualizar o arquivo."""

import io
import re
import zipfile
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
        # O openpyxl não salva o resultado das fórmulas; o Excel salvaria.
        "skip_reasons": {"fórmula sem resultado salvo (abra e salve no Excel)": 1},
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
    detail = response.json()["detail"]
    # A mensagem diz o que encontrou e o que falta, para dar para ajustar sem abrir o arquivo.
    assert "Nome, Idade" in detail
    assert "Faltam colunas de: Data, Descrição, Valor" in detail
    assert _import(client, b"x", "planilha.ods").status_code == 415


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


def saved_by_excel(content: bytes, cached: dict[str, str]) -> bytes:
    """Simula um arquivo salvo pelo Excel: grava o resultado junto de cada fórmula."""
    source = zipfile.ZipFile(io.BytesIO(content))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                xml = data.decode()
                for ref, value in cached.items():
                    xml = re.sub(
                        rf'(<c r="{ref}"[^>]*>)(<f>[^<]*</f>)<v ?/>',
                        rf"\g<1>\g<2><v>{value}</v>",
                        xml,
                    )
                data = xml.encode()
            target.writestr(info, data)
    return output.getvalue()


def formula_workbook() -> bytes:
    """Valor calculado por fórmula (quantidade × unitário), como em muitas planilhas reais."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Data", "Descrição", "Qtd", "Unitário", "Valor (R$)"])
    ws.append([datetime(2026, 9, 1), "Tubo de cobre", 2, 130, "=C2*D2"])
    ws.append([datetime(2026, 9, 2), "Fita isolante", 3, 10, "=C3*D3"])
    ws.append([datetime(2026, 9, 3), "Porca", 1, 5, "=C4*D4"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_valor_calculado_por_formula_usa_o_resultado_salvo(client):
    # Excel salvou o resultado das duas primeiras; a terceira ficou sem (arquivo editado fora dele).
    content = saved_by_excel(formula_workbook(), {"E2": "260", "E3": "30"})
    result = _import(client, content).json()
    assert result["imported"] == 2
    assert result["skip_reasons"] == {"fórmula sem resultado salvo (abra e salve no Excel)": 1}
    items = client.get("/api/expenses/items").json()["items"]
    assert sorted(i["total_cents"] for i in items) == [3000, 26000]


def test_atualizar_preserva_as_formulas_da_empresa(client):
    content = saved_by_excel(formula_workbook(), {"E2": "260", "E3": "30", "E4": "5"})
    client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-09-10",
            "description": "Aluguel",
            "items": [{"description": "Aluguel", "total_cents": 250000}],
            "entry_type": "Despesas",
        },
    )
    response = client.post(
        "/api/expenses/spreadsheet/update", files={"file": ("controle.xlsx", content)}
    )
    ws = load_workbook(io.BytesIO(response.content))["Sheet"]
    assert [ws["E2"].value, ws["E3"].value, ws["E4"].value] == ["=C2*D2", "=C3*D3", "=C4*D4"]


# --- outros formatos -------------------------------------------------------------------------


def test_le_excel_antigo_xls(client):
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Controle")
    date_style = xlwt.easyxf(num_format_str="DD/MM/YYYY")
    for col, header in enumerate(["Data", "Cliente/Fornecedor", "Descrição", "Tipo", "Valor (R$)"]):
        sheet.write(0, col, header)
    sheet.write(1, 0, datetime(2026, 8, 3), date_style)
    sheet.write(1, 1, "Frigelar")
    sheet.write(1, 2, "Tubo de cobre")
    sheet.write(1, 3, "Custo")
    sheet.write(1, 4, 327.6)
    buffer = io.BytesIO()
    book.save(buffer)

    result = _import(client, buffer.getvalue(), "controle-antigo.xls").json()
    assert result["imported"] == 1
    item = client.get("/api/expenses/items").json()["items"][0]
    assert (item["issue_date"], item["counterpart"], item["total_cents"]) == (
        "2026-08-03",
        "Frigelar",
        32760,
    )

    # Atualizar um .xls devolve .xlsx (o formato antigo não é regravado).
    xls_file = {"file": ("controle-antigo.xls", buffer.getvalue())}
    response = client.post("/api/expenses/spreadsheet/update", files=xls_file)
    assert "controle-antigo-atualizada.xlsx" in response.headers["content-disposition"]


def test_le_csv_do_excel_brasileiro(client):
    lines = [
        "Data;Mês;Cliente/Fornecedor;Proposta;Descrição;Tipo;Valor (R$)",
        "03/08/2026;ago/26;Frigelar;P-9;Fita isolante;Custo;1.234,56",
        "04/08/2026;ago/26;Vivo;;Internet;Despesas;119,99",
    ]
    content = "\n".join(lines).encode("cp1252")  # como o Excel brasileiro salva
    result = _import(client, content, "controle.csv").json()
    assert result["imported"] == 2
    totals = sorted(i["total_cents"] for i in client.get("/api/expenses/items").json()["items"])
    assert totals == [11999, 123456]


def test_xlsm_volta_como_xlsm(client):
    response = client.post(
        "/api/expenses/spreadsheet/update", files={"file": ("controle.xlsm", company_workbook())}
    )
    assert response.status_code == 200
    assert "controle-atualizada.xlsm" in response.headers["content-disposition"]
    assert "macroEnabled" in response.headers["content-type"]
