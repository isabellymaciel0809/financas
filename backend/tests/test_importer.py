from datetime import date

import pytest

from app.services.importer import (
    StatementParseError,
    fingerprints,
    parse_amount_cents,
    parse_file,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", 123456),
        ("-1234.56", -123456),
        ("R$ 10,00", 1000),
        ("(10,00)", -1000),
        ("10,00-", -1000),
        ("-0,99", -99),
        ("1,234.56", 123456),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount_cents(raw) == expected


def test_nubank_conta():
    csv = (
        "Data,Valor,Identificador,Descrição\n"
        "01/10/2026,-45.90,abc,Compra no débito - IFD*IFOOD\n"
        "05/10/2026,6500.00,def,Transferência recebida - Salário\n"
    ).encode()
    parsed = parse_file("nubank.csv", csv)
    assert parsed.source_format == "nubank_conta"
    assert parsed.rows[0].date == date(2026, 10, 1)
    assert parsed.rows[0].amount_cents == -4590
    assert parsed.rows[1].amount_cents == 650000


def test_nubank_cartao_inverte_sinal():
    csv = b"date,title,amount\n2026-10-03,Uber *Trip,23.50\n2026-10-04,Pagamento recebido,-500.00\n"
    parsed = parse_file("fatura.csv", csv)
    assert parsed.source_format == "nubank_cartao"
    assert [r.amount_cents for r in parsed.rows] == [-2350, 50000]


def test_inter_com_linhas_antes_do_cabecalho_e_latin1():
    csv = (
        "Extrato Conta Corrente\n"
        "Conta ;12345\n"
        "\n"
        "Data Lançamento;Histórico;Descrição;Valor;Saldo\n"
        "02/10/2026;Pix enviado;Padaria Pão Quente;-12,50;987,50\n"
        "03/10/2026;Compra no debito;Supermercado Dia;-1.050,00;-62,50\n"
    ).encode("cp1252")
    parsed = parse_file("inter.csv", csv)
    assert parsed.source_format == "inter"
    assert parsed.rows[0].description == "Pix enviado - Padaria Pão Quente"
    assert parsed.rows[1].amount_cents == -105000


def test_ofx():
    ofx = b"""OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261010120000[-3:BRT]<TRNAMT>-89.90<MEMO>DROGASIL 123
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261011<TRNAMT>100.00<NAME>PIX RECEBIDO
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    parsed = parse_file("extrato.ofx", ofx)
    assert parsed.source_format == "ofx"
    assert [(r.date, r.amount_cents, r.description) for r in parsed.rows] == [
        (date(2026, 10, 10), -8990, "DROGASIL 123"),
        (date(2026, 10, 11), 10000, "PIX RECEBIDO"),
    ]


def test_arquivo_sem_cabecalho_valido():
    with pytest.raises(StatementParseError):
        parse_file("x.csv", b"foo,bar\n1,2\n")


def test_fingerprint_distingue_transacoes_iguais_no_mesmo_arquivo():
    csv = b"Data,Valor,Descricao\n01/10/2026,-5.00,Cafe\n01/10/2026,-5.00,Cafe\n"
    rows = parse_file("a.csv", csv).rows
    first, second = fingerprints(rows)
    assert first != second
    assert fingerprints(rows) == [first, second]  # estável entre importações
