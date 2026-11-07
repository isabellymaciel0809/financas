"""Leitor determinístico do texto de um cupom NFC-e (DANFE NFC-e) vindo do OCR.

Por que não usar só a LLM? Testado com qwen2.5:3b na CPU, extrair um cupom de 23 itens passou
de 30 minutos: o modelo entra em loop com linhas repetidas (10 itens idênticos). O layout do
DANFE NFC-e é padronizado, então padrões resolvem em milissegundos; o que não fecha vai para
revisão humana com o problema apontado.

Formatos de item observados no OCR:
  "DESCRIÇÃO  2,83  2,83"  +  "CÓDIGO  1,000PC"           (quantidade na linha seguinte)
  "CÓDIGO  DESCRIÇÃO  1,000PC  25,41  25,41"              (tudo numa linha)
  "CÓDIGO  33,04" ou "70,50"                              (OCR perdeu a descrição)
"""

import re
from datetime import date

from app.services.fiscal.extracted import ExtractedDocument, ExtractedItem
from app.services.fiscal.keys import is_valid_cnpj, only_digits
from app.services.text import simplify

ILLEGIBLE = "(descrição ilegível)"

# Valor monetário: 2,83 | 1.034,33 | 1034.33 | 1.034.33 (OCR troca vírgula por ponto)
_MONEY = r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2}"
_TRAILING_AMOUNTS = re.compile(rf"(?:^|\s)({_MONEY})(?:\s+({_MONEY}))?\s*$")
# Quantidade + unidade: 1,000PC | 5.000 PC | 2,520KG | 50,000MT
_QTY = re.compile(r"(\d+[.,]\d{3})\s*([A-Za-z]{2,3})\b")
# Código do produto no começo da linha: letras e dígitos (pelo menos 3 dígitos), terminando no
# último dígito, porque o OCR às vezes cola o código na descrição ("00C151368MANOMETRO").
_CODE = re.compile(r"^((?=[0-9A-Z]*\d{3})[0-9A-Z]{4,13}\d)(?=\s|[A-Z]{2}|$)")
_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_NUMBER = re.compile(r"(?:N[º°oO*]|Numero|Número)\s*[:.]?\s*(\d{3,9})", re.IGNORECASE)

PAYMENT_WORDS = {
    "debito": "Cartão de débito",
    "credito": "Cartão de crédito",
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "boleto": "Boleto",
}


def parse_money(text: str) -> int:
    """Último separador seguido de 2 dígitos é o decimal; os demais são milhar."""
    digits = only_digits(text)
    return int(digits) if digits else 0


def _parse_quantity(text: str) -> float:
    return float(text.replace(",", "."))


def _is_header(line: str) -> bool:
    s = simplify(line)
    return "descri" in s or ("cod" in s and "unit" in s)


def _is_footer(line: str) -> bool:
    s = simplify(line).replace(" ", "")
    return any(word in s for word in ("total", "pagar", "pagamento", "troco", "consulte"))


def parse_receipt_lines(lines: list[str]) -> ExtractedDocument:
    header_end = next((i for i, line in enumerate(lines) if _is_header(line)), -1)
    footer_start = next(
        (i for i in range(header_end + 1, len(lines)) if _is_footer(lines[i])), len(lines)
    )
    items = _parse_items(lines[header_end + 1 : footer_start])
    footer = lines[footer_start:]
    full_text = "\n".join(lines)

    return ExtractedDocument(
        items=items,
        issuer_name=_issuer_name(lines[: max(header_end, 0)]),
        issuer_cnpj=_cnpj(full_text),
        issue_date=_issue_date(full_text),
        number=_number(full_text),
        total_cents=_total(footer),
        declared_item_count=_declared_count(footer),
        payment_method=_payment(footer),
    )


def _parse_items(lines: list[str]) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    consumed: set[int] = set()
    for index, line in enumerate(lines):
        if index in consumed:
            continue
        amounts = _TRAILING_AMOUNTS.search(line)
        if amounts is None:
            continue
        first, second = amounts.group(1), amounts.group(2)
        total = parse_money(second or first)
        unit_price = parse_money(first) if second else None
        body = line[: amounts.start()].strip()

        quantity, unit = None, None
        qty_match = _QTY.search(body)
        if qty_match:
            quantity, unit = _parse_quantity(qty_match.group(1)), qty_match.group(2).upper()
            body = (body[: qty_match.start()] + body[qty_match.end() :]).strip()

        code = None
        code_match = _CODE.match(body)
        if code_match:
            code, body = code_match.group(1), body[code_match.end() :].strip()

        # Quantidade (e às vezes o código) na linha seguinte, que não tem valores no fim.
        following = index + 1
        if (
            quantity is None
            and following < len(lines)
            and _TRAILING_AMOUNTS.search(lines[following]) is None
        ):
            next_qty = _QTY.search(lines[following])
            if next_qty:
                quantity, unit = _parse_quantity(next_qty.group(1)), next_qty.group(2).upper()
                rest = lines[following][: next_qty.start()].strip()
                if code is None and _CODE.match(rest + " "):
                    code = _CODE.match(rest + " ").group(1)
                consumed.add(following)

        if quantity is None:
            quantity = round(total / unit_price, 3) if unit_price else 1.0
        if unit_price is None and quantity:
            unit_price = round(total / quantity)

        description = re.sub(r"\s{2,}", " ", body).strip(" -")
        if not description and code:
            # OCR perdeu a descrição, mas o mesmo código já apareceu: reaproveita.
            previous = next((i for i in reversed(items) if i.code == code), None)
            if previous is not None:
                description, unit = previous.description, unit or previous.unit
                if previous.total_cents == total:
                    quantity, unit_price = previous.quantity, previous.unit_price_cents
        items.append(
            ExtractedItem(
                description=description or ILLEGIBLE,
                total_cents=total,
                quantity=quantity,
                unit=unit,
                unit_price_cents=unit_price,
                code=code,
            )
        )
    return items


def _issuer_name(header: list[str]) -> str | None:
    for line in header:
        s = simplify(line)
        if any(word in s.split() or s.endswith(word) for word in ("ltda", "eireli", "sa", "me")):
            return re.sub(r"\s{2,}", " ", line).strip()
    return header[0].strip() if header else None


def _cnpj(text: str) -> str | None:
    for match in _CNPJ.finditer(text):
        if is_valid_cnpj(match.group(0)):
            return only_digits(match.group(0))
    return None


def _issue_date(text: str) -> date | None:
    for day, month, year in _DATE.findall(text):
        try:
            found = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if 2000 <= found.year <= date.today().year:
            return found
    return None


def _number(text: str) -> str | None:
    match = _NUMBER.search(text)
    return match.group(1).lstrip("0") or None if match else None


def _total(footer: list[str]) -> int | None:
    # "Valor total" costuma ser o maior valor do rodapé (troco e descontos são menores).
    values = [parse_money(m) for line in footer for m in re.findall(_MONEY, line)]
    return max(values) if values else None


def _declared_count(footer: list[str]) -> int | None:
    for line in footer:
        s = simplify(line).replace(" ", "")
        if "total" in s and any(w in s for w in ("iten", "tens", "tons", "itns")):
            numbers = [n for n in re.findall(r"(?<![\d.,])\d{1,4}(?![\d.,])", line)]
            if numbers:
                return int(numbers[-1])
    return None


def _payment(footer: list[str]) -> str | None:
    for line in footer:
        s = simplify(line)
        for word, label in PAYMENT_WORDS.items():
            if word in s:
                return label
    return None
