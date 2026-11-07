"""Leitor de cupom por padrões. As linhas imitam a saída real do OCR de um cupom NFC-e
(erros de leitura incluídos), sem dados do consumidor."""

from datetime import date

from app.services.categorizer.rules import match_rule
from app.services.fiscal.receipt_parser import parse_money, parse_receipt_lines

OCR_LINES = [
    "FRIGELAR COMERCIO E INDUSTRIA LTDA",
    "CNPJ 92.660.406/0059-35  I.E. 138822009111",
    "Docunento Auxiltar da Nota Fiscn Consunidor Eletranica",
    "Codi90  Descricio  Otde UN  U1Unit  U1 Total",
    # descrição e valores; código e quantidade na linha seguinte
    "FITAPUC10NLINEARX0.10  LARG  2.83",
    "005103837  1.000PC",
    # código + descrição + valores; quantidade na linha seguinte
    "00S103837  FITAPUC10LINEARX0.10HLARG  2,83  2.83",
    "1,000PC",
    # tudo numa linha, código colado na descrição
    "00C151368HANOMETR0ALTAR22/134A/404A/R407C  1.000PC  25,41  25,41",
    # quantidade maior que 1
    "00C169772  2UNIAOC/UALUULATIPOSCHRADER1/4S  3,26  16,30",
    "5,000PC",
    # quantidade ilegível: deduzida de total / unitário
    "00C200757 TUB0 ISOLANTE POLIETILENO BLINDAD0  Jd000'8  4.13  33.04",
    # OCR perdeu a descrição: reaproveita a do mesmo código
    "00C200757  33.04",
    # quilo, com milhar
    "00T218636  TUBO COBRE PANQUECA 1/2  2,520KG  130,00  327,60",
    "Qtde total de itens  7",
    "Valor total R$  441,05",
    "FORMA PAGAMENTO  VALOR PAGO R$",
    "Cartao Debito  441,05",
    "NFC-e Nº 000002425 Serie 9 03/11/2026 10:19:59",
]


def test_valores_com_separadores_do_ocr():
    assert parse_money("2,83") == 283
    assert parse_money("1.034,33") == 103433
    assert parse_money("1.034.33") == 103433  # OCR trocou a vírgula por ponto


def test_le_cupom_e_fecha_a_soma():
    doc = parse_receipt_lines(OCR_LINES)

    assert doc.issuer_name == "FRIGELAR COMERCIO E INDUSTRIA LTDA"
    assert doc.issuer_cnpj == "92660406005935"
    assert doc.issue_date == date(2026, 11, 3)
    assert doc.number == "2425"
    assert doc.total_cents == 44105
    assert doc.declared_item_count == 7
    assert doc.payment_method == "Cartão de débito"

    got = [(i.code, i.quantity, i.unit, i.unit_price_cents, i.total_cents) for i in doc.items]
    assert got == [
        ("005103837", 1.0, "PC", 283, 283),
        ("00S103837", 1.0, "PC", 283, 283),
        ("00C151368", 1.0, "PC", 2541, 2541),
        ("00C169772", 5.0, "PC", 326, 1630),
        ("00C200757", 8.0, None, 413, 3304),
        ("00C200757", 8.0, None, 413, 3304),
        ("00T218636", 2.52, "KG", 13000, 32760),
    ]
    assert sum(i.total_cents for i in doc.items) == doc.total_cents
    assert doc.items[2].description == "HANOMETR0ALTAR22/134A/404A/R407C"
    assert doc.items[5].description == doc.items[4].description  # descrição reaproveitada


def test_regras_toleram_erros_de_ocr_so_em_itens():
    assert match_rule("TUB0 ISOLANTE POLIETILENO", -100, ocr_tolerant=True) == (
        "Materiais e manutenção"
    )
    assert match_rule("FITAPUC10LINEARX0.10HLARG", -100, ocr_tolerant=True) == (
        "Materiais e manutenção"
    )
    assert match_rule("2UNIAOC/UALUULATIPOSCHRADER", -100, ocr_tolerant=True) == (
        "Materiais e manutenção"
    )
    # Sem a tolerância (extrato bancário), palavra grudada não casa.
    assert match_rule("FITAPUC10LINEARX0.10HLARG", -100) is None
    # Palavra-chave curta não casa pelo começo ("bar" não pega "barbeador").
    assert match_rule("BARBEADOR DESCARTAVEL", -100, ocr_tolerant=True) is None
