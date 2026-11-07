import io
from datetime import date

import pytest
from openpyxl import load_workbook

from app.models import Expense, ExpenseSource, ExpenseStatus
from app.services.fiscal import processor
from app.services.fiscal.extracted import ExtractedDocument, ExtractedItem
from app.services.fiscal.keys import _mod11, format_cnpj, is_valid_cnpj, parse_access_key
from app.services.fiscal.nfe_xml import NFeParseError, parse_nfe_xml
from app.services.fiscal.photo import _from_llm
from app.services.fiscal.validation import validate

FRIGELAR = "92660406005935"  # CNPJ real lido de um cupom (dígitos verificadores conferem)


def make_key(cnpj: str = FRIGELAR, model: str = "55", number: int = 1234) -> str:
    base = f"352611{cnpj}{model}001{number:09d}112345678"
    return base + str(_mod11(base, [2, 3, 4, 5, 6, 7, 8, 9]))


def make_nfe_xml(key: str | None = None, freight: str = "15.00") -> bytes:
    key = key or make_key()
    total = f"{53.30 + float(freight):.2f}"  # produtos - desconto + frete
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
 <NFe><infNFe Id="NFe{key}" versao="4.00">
  <ide><mod>55</mod><serie>1</serie><nNF>1234</nNF><dhEmi>2026-11-03T10:15:00-03:00</dhEmi></ide>
  <emit><CNPJ>{FRIGELAR}</CNPJ><xNome>FRIGELAR COMERCIO E INDUSTRIA LTDA</xNome>
        <xFant>FRIGELAR</xFant></emit>
  <det nItem="1"><prod><cProd>S103837</cProd><xProd>FITA PVC 10M LINEAR</xProd>
    <NCM>39191000</NCM><uCom>PC</uCom><qCom>10.0000</qCom><vUnCom>2.8300</vUnCom>
    <vProd>28.30</vProd></prod></det>
  <det nItem="2"><prod><cProd>C151388</cProd><xProd>MANOMETRO ALTA R22/134A</xProd>
    <NCM>90262010</NCM><uCom>PC</uCom><qCom>1.0000</qCom><vUnCom>25.4100</vUnCom>
    <vProd>25.41</vProd><vDesc>0.41</vDesc></prod></det>
  <total><ICMSTot><vProd>53.71</vProd><vDesc>0.41</vDesc><vFrete>{freight}</vFrete>
    <vNF>{total}</vNF></ICMSTot></total>
  <pag><detPag><tPag>17</tPag><vPag>{total}</vPag></detPag></pag>
 </infNFe></NFe>
</nfeProc>""".encode()


# --- chaves e CNPJ ---------------------------------------------------------------------------


def test_cnpj():
    assert is_valid_cnpj(FRIGELAR)
    assert is_valid_cnpj("92.660.406/0059-35")
    assert not is_valid_cnpj("92660406005936")  # dígito trocado
    assert not is_valid_cnpj("11111111111111")
    assert format_cnpj(FRIGELAR) == "92.660.406/0059-35"


def test_chave_de_acesso_da_url_do_qrcode():
    key = make_key(model="65", number=2425)
    parsed = parse_access_key(f"https://www.nfce.fazenda.sp.gov.br/qrcode?p={key}|2|1|1|ABCDEF")
    assert parsed is not None
    assert (parsed.uf, parsed.issuer_cnpj, parsed.model, parsed.number, parsed.series) == (
        "35",
        FRIGELAR,
        "65",
        "2425",
        "1",
    )
    assert parsed.year_month == date(2026, 11, 1)


def test_chave_impressa_em_grupos_e_digito_errado():
    key = make_key()
    grouped = " ".join(key[i : i + 4] for i in range(0, 44, 4))
    assert parse_access_key(f"Consulte pela chave: {grouped}").digits == key
    wrong = key[:10] + str((int(key[10]) + 1) % 10) + key[11:]  # um dígito lido errado
    assert parse_access_key(wrong) is None


# --- XML -------------------------------------------------------------------------------------


def test_le_xml_de_nfe():
    doc = parse_nfe_xml(make_nfe_xml())
    assert doc.access_key == make_key()
    assert (doc.model, doc.number, doc.series) == ("55", "1234", "1")
    assert doc.issue_date == date(2026, 11, 3)
    assert (doc.issuer_cnpj, doc.issuer_name) == (FRIGELAR, "FRIGELAR")
    assert doc.total_cents == 6830  # inclui o frete
    assert doc.items_expected_cents == 5330  # produtos - desconto
    assert doc.payment_method == "Pix"
    assert [(i.description, i.quantity, i.total_cents, i.ncm) for i in doc.items] == [
        ("FITA PVC 10M LINEAR", 10.0, 2830, "39191000"),
        ("MANOMETRO ALTA R22/134A", 1.0, 2500, "90262010"),  # já com desconto
    ]


def test_xml_com_frete_nao_acusa_diferenca():
    doc = parse_nfe_xml(make_nfe_xml())
    issues = validate(
        items=[(i.quantity, i.unit_price_cents, i.total_cents) for i in doc.items],
        items_expected_cents=doc.items_expected_cents,
        total_cents=doc.total_cents,
        declared_item_count=doc.declared_item_count,
        issuer_cnpj=doc.issuer_cnpj,
        has_issue_date=True,
    )
    # Só o desconto do manômetro aparece: 1 × 25,41 ≠ 25,00. É informativo e esperado.
    assert len(issues) == 1 and "Item 2" in issues[0]


def test_xml_malicioso_e_rejeitado():
    xxe = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
<x>&e;</x>"""
    with pytest.raises(NFeParseError):
        parse_nfe_xml(xxe)
    with pytest.raises(NFeParseError):
        parse_nfe_xml(b"<html>nao e nota</html>")


# --- validações ------------------------------------------------------------------------------


def test_validacoes_do_cupom():
    ok = validate(
        items=[(10, 283, 2830), (1, 1368, 1368)],
        items_expected_cents=4198,
        total_cents=4198,
        declared_item_count=2,
        issuer_cnpj=FRIGELAR,
        has_issue_date=True,
    )
    assert ok == []

    problems = validate(
        items=[(10, 283, 2830)],
        items_expected_cents=103433,
        total_cents=103433,
        declared_item_count=23,
        issuer_cnpj="92660406005936",
        has_issue_date=False,
        uncategorized=1,
    )
    assert any("faltam R$ 1.006,03" in p for p in problems)
    assert any("informa 23 itens, mas 1" in p for p in problems)
    assert any("CNPJ do fornecedor inválido" in p for p in problems)
    assert any("Data de emissão" in p for p in problems)
    assert any("sem categoria" in p for p in problems)


def test_resposta_da_llm_vira_documento():
    doc = _from_llm(
        {
            "emitente_nome": "FRIGELAR",
            "emitente_cnpj": "92.660.406/0059-35",
            "data_emissao": "03/11/2026",
            "numero_nota": "000002425",
            "itens": [
                {
                    "codigo": "00S103837",
                    "descricao": "FITA PVC 10 M",
                    "quantidade": 1,
                    "unidade": "PC",
                    "valor_unitario": 2.83,
                    "valor_total": 2.83,
                },
                {
                    "codigo": "",
                    "descricao": "",
                    "quantidade": 1,
                    "unidade": "",
                    "valor_unitario": 0,
                    "valor_total": 1,
                },  # sem descrição: descartado
            ],
            "qtd_total_itens": 23,
            "valor_total": 1034.33,
            "forma_pagamento": "Cartão Débito",
        }
    )
    assert doc.issuer_cnpj == FRIGELAR
    assert doc.number == "2425"
    assert doc.issue_date == date(2026, 11, 3)
    assert doc.total_cents == doc.items_expected_cents == 103433
    assert [(i.description, i.total_cents) for i in doc.items] == [("FITA PVC 10 M", 283)]


# --- processamento e API ---------------------------------------------------------------------


def _upload(client, name: str, content: bytes):
    return client.post("/api/expenses/upload", files=[("files", (name, content))])


def test_upload_de_xml_lanca_automaticamente(client):
    response = _upload(client, "nota.xml", make_nfe_xml(freight="0.00"))
    assert response.status_code == 202
    expense_id = response.json()[0]["id"]

    # O TestClient executa a fila em segundo plano antes de devolver a resposta.
    detail = client.get(f"/api/expenses/{expense_id}").json()
    assert detail["supplier"]["name"] == "FRIGELAR"
    assert detail["total_cents"] == 5330
    categories = [i["category"]["name"] for i in detail["items"]]
    assert categories == ["Materiais e manutenção", "Ferramentas e equipamentos"]  # por regras
    # O desconto do manômetro gera um aviso (quantidade × unitário ≠ total): vai para revisão.
    assert detail["status"] == "needs_review"
    assert client.post(f"/api/expenses/{expense_id}/confirm").json()["status"] == "confirmed"


def test_mesma_nota_duas_vezes_vira_duplicata(client):
    first = _upload(client, "nota.xml", make_nfe_xml()).json()[0]["id"]
    second = _upload(client, "copia.xml", make_nfe_xml()).json()[0]["id"]
    detail = client.get(f"/api/expenses/{second}").json()
    assert detail["status"] == "duplicate"
    assert f"#{first}" in detail["issues"][0]


def test_arquivo_de_tipo_errado(client):
    assert _upload(client, "planilha.csv", b"a,b").status_code == 415


def test_foto_com_qr_ilegivel_vai_para_revisao(client, monkeypatch):
    def fake_read_photo(content, provider, use_llm_fallback=False):
        return ExtractedDocument(
            items=[ExtractedItem("FITA PVC 10 M LINEAR", 283, 1, "PC", 283)],
            issuer_cnpj=FRIGELAR,
            issuer_name="FRIGELAR",
            issue_date=date(2026, 11, 3),
            total_cents=283,
            items_expected_cents=283,
            declared_item_count=1,
            notes=["QR Code ilegível."],
        )

    monkeypatch.setattr(processor, "read_photo", fake_read_photo)
    expense_id = _upload(client, "cupom.jpg", b"\xff\xd8 fake").json()[0]["id"]
    detail = client.get(f"/api/expenses/{expense_id}").json()
    assert detail["status"] == "needs_review"
    assert detail["issues"] == ["QR Code ilegível."]
    assert detail["source"] == "photo"
    assert client.get(f"/api/expenses/{expense_id}/file").content == b"\xff\xd8 fake"


def test_lancamento_manual_de_funcionario_e_reembolso(client):
    employee = client.post("/api/employees", json={"name": "Ana Souza", "role": "Técnica"}).json()
    response = client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-05",
            "description": "Almoço em visita técnica",
            "employee_id": employee["id"],
            "reimbursable": True,
            "items": [{"description": "Almoço restaurante", "total_cents": 4590}],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["total_cents"] == 4590
    assert body["items"][0]["category"]["name"] == "Alimentação"  # regra "restaurante"
    assert body["employee"]["name"] == "Ana Souza"


def test_correcao_de_categoria_na_revisao_vira_memoria(client, db):
    expense_id = _upload(client, "nota.xml", make_nfe_xml()).json()[0]["id"]
    detail = client.get(f"/api/expenses/{expense_id}").json()
    tools = next(
        c["id"]
        for c in client.get("/api/categories").json()
        if c["name"] == "Ferramentas e equipamentos"
    )
    items = [
        {
            "id": i["id"],
            "description": i["description"],
            "total_cents": i["total_cents"],
            "quantity": i["quantity"],
            "unit_price_cents": None,
            "category_id": tools if i["position"] == 1 else i["category"]["id"],
        }
        for i in detail["items"]
    ]
    updated = client.patch(f"/api/expenses/{expense_id}", json={"items": items}).json()
    assert [i["categorized_by"] for i in updated["items"]] == ["manual", "rule"]
    assert updated["status"] == "confirmed"  # sem o unitário, a divergência do desconto sumiu

    # Na próxima nota com o mesmo item, a memória vence a regra.
    other = _upload(client, "outra.xml", make_nfe_xml(key=make_key(number=999))).json()[0]["id"]
    first_item = client.get(f"/api/expenses/{other}").json()["items"][0]
    assert (first_item["category"]["name"], first_item["categorized_by"]) == (
        "Ferramentas e equipamentos",
        "memory",
    )


def test_exportacao_excel(client):
    employee = client.post("/api/employees", json={"name": "Ana Souza"}).json()
    client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-05",
            "description": "Combustível da van",
            "employee_id": employee["id"],
            "reimbursable": True,
            "items": [{"description": "Posto Shell gasolina", "total_cents": 20000}],
        },
    )
    response = client.get("/api/expenses/export.xlsx", params={"month": "2026-11"})
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == [
        "Planilha",
        "Por proposta",
        "Por categoria",
        "Reembolsos",
        "Notas",
    ]
    assert [c.value for c in workbook["Reembolsos"][2]] == ["Ana Souza", 200.0]
    notes = [c.value for c in workbook["Notas"][2]]
    assert notes[6:9] == ["Despesas", "Ana Souza", "Sim"]


def test_planilha_no_formato_da_empresa_uma_linha_por_item(client):
    """Data | Mês | Cliente/Fornecedor | Proposta | Descrição | Tipo | Valor (R$)."""
    upload = client.post(
        "/api/expenses/upload",
        files=[("files", ("nota.xml", make_nfe_xml(freight="0.00")))],
        data={"proposal": "P-123"},
    ).json()[0]
    assert (upload["proposal"], upload["entry_type"]) == ("P-123", "Custo")  # com proposta
    client.post(f"/api/expenses/{upload['id']}/confirm")
    receita = next(
        c["id"] for c in client.get("/api/categories").json() if c["name"] == "Receita de serviços"
    )
    income = client.post(
        "/api/expenses",
        json={
            "issue_date": "2026-11-20",
            "description": "Instalação de câmara fria",
            "supplier_name": "Mercado Bom Preço",
            "proposal": "P-123",
            "entry_type": "Receita",
            "items": [
                {
                    "description": "Instalação de câmara fria",
                    "total_cents": 150000,
                    "category_id": receita,
                }
            ],
        },
    ).json()
    assert income["status"] == "confirmed"

    workbook = load_workbook(
        io.BytesIO(client.get("/api/expenses/export.xlsx", params={"month": "2026-11"}).content)
    )
    sheet = workbook["Planilha"]
    assert [c.value for c in sheet[1]] == [
        "Data",
        "Mês",
        "Cliente/Fornecedor",
        "Proposta",
        "Descrição",
        "Tipo",
        "Valor (R$)",
    ]
    rows = [[c.value for c in row] for row in sheet.iter_rows(min_row=2)]
    assert len(rows) == 3  # 2 itens da nota + 1 receita
    first = rows[0]
    assert first[0].date() == date(2026, 11, 3)
    assert first[1].date() == date(2026, 11, 1)  # mês como data, exibido "nov/26"
    assert sheet["B2"].number_format == "MMM/YY"
    assert first[2:] == ["FRIGELAR", "P-123", "FITA PVC 10M LINEAR", "Custo", 28.3]
    assert rows[2][2:] == [
        "Mercado Bom Preço",
        "P-123",
        "Instalação de câmara fria",
        "Receita",
        1500.0,
    ]

    by_proposal = [[c.value for c in row] for row in workbook["Por proposta"].iter_rows(min_row=2)]
    assert by_proposal == [["P-123", 1500.0, 53.3, 0.0, 1446.7]]


def test_apply_extraction_sem_itens_vai_para_revisao(db):
    expense = Expense(source=ExpenseSource.photo, stored_filename="x.jpg", issues=[])
    db.add(expense)
    db.flush()
    processor.apply_extraction(db, expense, ExtractedDocument(total_cents=1000), provider=None)
    assert expense.status == ExpenseStatus.needs_review
    assert "Nenhum item foi identificado." in expense.issues
