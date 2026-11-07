"""Leitura de extratos (CSV de bancos brasileiros e OFX) em um formato comum."""

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.services.text import simplify


class StatementParseError(ValueError):
    """Arquivo em formato não reconhecido ou sem transações válidas."""


@dataclass(frozen=True)
class ParsedRow:
    date: date
    description: str
    amount_cents: int  # negativo = despesa


@dataclass
class ParsedFile:
    source_format: str
    rows: list[ParsedRow]


DATE_ALIASES = {"data", "date", "data lancamento", "data da transacao", "data movimento", "dt"}
AMOUNT_ALIASES = {"valor", "amount", "valor r", "valor rs", "valor em r", "quantia"}
# Em ordem de prioridade; quando há mais de uma coluna, os textos são concatenados.
DESCRIPTION_ALIASES = [
    "historico",
    "descricao",
    "description",
    "title",
    "estabelecimento",
    "lancamento",
    "memo",
]
DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%Y/%m/%d")


def decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StatementParseError("Não foi possível ler o arquivo (codificação desconhecida).")


def parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {raw!r}")


def parse_amount_cents(raw: str) -> int:
    """Aceita "1.234,56", "-1234.56", "R$ 10,00", "(10,00)" e "10,00-"."""
    text = raw.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"valor inválido: {raw!r}") from exc
    cents = int((value * 100).quantize(Decimal("1")))
    return -cents if negative else cents


def parse_file(filename: str, content: bytes) -> ParsedFile:
    text = decode(content)
    if filename.lower().endswith(".ofx") or "<OFX>" in text.upper():
        return _parse_ofx(text)
    return _parse_csv(text)


def _parse_csv(text: str) -> ParsedFile:
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    lines = list(csv.reader(io.StringIO(text), delimiter=delimiter))

    # Alguns bancos (ex.: Inter) colocam linhas de cabeçalho antes da tabela.
    header_idx = None
    for idx, line in enumerate(lines[:30]):
        cells = {simplify(c) for c in line}
        if cells & DATE_ALIASES and cells & AMOUNT_ALIASES:
            header_idx = idx
            break
    if header_idx is None:
        raise StatementParseError(
            "Cabeçalho não encontrado. O CSV precisa ter colunas de data, descrição e valor."
        )

    header = [simplify(c) for c in lines[header_idx]]
    date_col = next(i for i, h in enumerate(header) if h in DATE_ALIASES)
    amount_col = next(i for i, h in enumerate(header) if h in AMOUNT_ALIASES)
    desc_cols = [header.index(a) for a in DESCRIPTION_ALIASES if a in header]
    if not desc_cols:
        raise StatementParseError("Coluna de descrição não encontrada no CSV.")

    header_set = set(header)
    if {"title", "amount"} <= header_set:
        # Fatura do cartão Nubank: valores positivos são compras.
        source_format, invert_sign = "nubank_cartao", True
    elif "identificador" in header_set:
        source_format, invert_sign = "nubank_conta", False
    elif "historico" in header_set:
        source_format, invert_sign = "inter", False
    else:
        source_format, invert_sign = "csv_generico", False

    rows: list[ParsedRow] = []
    for line in lines[header_idx + 1 :]:
        if len(line) <= max(date_col, amount_col, *desc_cols) or not line[date_col].strip():
            continue
        try:
            row_date = parse_date(line[date_col])
            amount = parse_amount_cents(line[amount_col])
        except ValueError:
            continue  # linhas de saldo, totais, rodapé etc.
        parts: list[str] = []
        for col in desc_cols:
            value = line[col].strip()
            if value and value not in parts:
                parts.append(value)
        description = " - ".join(parts) or "Sem descrição"
        rows.append(ParsedRow(row_date, description[:255], -amount if invert_sign else amount))

    if not rows:
        raise StatementParseError("Nenhuma transação válida encontrada no arquivo.")
    return ParsedFile(source_format, rows)


_OFX_TRANSACTION = re.compile(
    r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", re.S | re.I
)


def _ofx_field(block: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<\r\n]*)", block, re.I)
    return match.group(1).strip() if match else None


def _parse_ofx(text: str) -> ParsedFile:
    rows: list[ParsedRow] = []
    for block in _OFX_TRANSACTION.findall(text):
        raw_date = _ofx_field(block, "DTPOSTED")
        raw_amount = _ofx_field(block, "TRNAMT")
        description = _ofx_field(block, "MEMO") or _ofx_field(block, "NAME") or "Sem descrição"
        if not raw_date or not raw_amount:
            continue
        try:
            row_date = datetime.strptime(raw_date[:8], "%Y%m%d").date()
            amount = parse_amount_cents(raw_amount)
        except ValueError:
            continue
        rows.append(ParsedRow(row_date, description[:255], amount))
    if not rows:
        raise StatementParseError("Nenhuma transação encontrada no arquivo OFX.")
    return ParsedFile("ofx", rows)


def fingerprints(rows: list[ParsedRow]) -> list[str]:
    """Identificador estável por linha, para detectar reimportações.

    Inclui o número da ocorrência dentro do arquivo: dois cafés iguais no mesmo dia
    continuam sendo duas transações, mas importar o mesmo arquivo de novo não duplica.
    """
    seen: Counter[tuple] = Counter()
    result = []
    for row in rows:
        key = (row.date.isoformat(), row.amount_cents, simplify(row.description))
        seen[key] += 1
        raw = "|".join(map(str, (*key, seen[key])))
        result.append(hashlib.sha256(raw.encode()).hexdigest())
    return result
