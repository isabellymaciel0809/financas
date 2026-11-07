"""Integração com a planilha que a empresa já usa.

Colunas: Data | Mês | Cliente/Fornecedor | Proposta | Descrição | Tipo | Valor (R$)

- Importar: cada linha da planilha vira um lançamento confirmado (o histórico já foi conferido
  por quem preencheu). Reimportar o mesmo arquivo não duplica nada.
- Atualizar: recebe a planilha da empresa e devolve o MESMO arquivo com os lançamentos novos do
  sistema no fim da tabela. Abas, formatação e fórmulas existentes são preservadas, e linhas que
  já estão na planilha não são repetidas.
"""

import hashlib
import io
import logging
import re
from collections import Counter
from copy import copy
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseItem, ExpenseSource, ExpenseStatus
from app.routers.dashboard import month_range
from app.services.fiscal.importer_utils import parse_cell_amount, parse_cell_date
from app.services.fiscal.items import categorize_items
from app.services.fiscal.processor import upsert_supplier
from app.services.text import simplify

# Nome normalizado do cabeçalho -> campo. simplify("Valor (R$)") == "valor r".
HEADER_ALIASES = {
    "date": {"data", "data lancamento", "data de emissao"},
    "month": {"mes", "mes referencia", "competencia"},
    "counterpart": {"cliente fornecedor", "cliente", "fornecedor", "favorecido"},
    "proposal": {"proposta", "obra", "n proposta"},
    "description": {"descricao", "historico", "item"},
    "entry_type": {"tipo"},
    "value": {"valor r", "valor", "valor rs", "valor em r"},
}
logger = logging.getLogger(__name__)

REQUIRED = {"date", "description", "value"}
MAX_HEADER_SCAN = 20
# Formato para células novas quando a planilha não tem uma linha anterior para copiar.
DEFAULT_FORMATS = {"date": "DD/MM/YYYY", "month": "MMM/YY", "value": "#,##0.00"}


class SheetFormatError(ValueError):
    pass


@dataclass
class Table:
    ws: Worksheet
    header_row: int
    columns: dict[str, int]  # campo -> número da coluna (1 = A)


@dataclass
class SheetRow:
    row: int
    date: date
    counterpart: str | None
    proposal: str | None
    description: str
    entry_type: str
    cents: int


@dataclass
class ImportReport:
    sheet: str
    imported: int = 0
    duplicates: int = 0  # já importadas antes, desta ou de outra planilha
    already_in_system: int = 0  # já lançadas no sistema (nota, cupom ou manual)
    skipped: int = 0
    skipped_rows: list[int] = field(default_factory=list)


FIELD_LABELS = {"date": "Data", "description": "Descrição", "value": "Valor"}


def find_table(workbook) -> Table:
    """Procura, em todas as abas, a linha de cabeçalho com Data, Descrição e Valor.

    Se não encontrar, explica o que achou (cabeçalho mais provável e o que falta), para a
    pessoa ou o desenvolvedor ajustarem sem precisar abrir o arquivo.
    """
    best: tuple[int, str, int, list[str], set[str]] | None = None
    for ws in workbook.worksheets:
        for row in range(1, min(ws.max_row, MAX_HEADER_SCAN) + 1):
            columns: dict[str, int] = {}
            texts: list[str] = []
            for col in range(1, min(ws.max_column, 40) + 1):
                value = ws.cell(row, col).value
                if not isinstance(value, str) or not value.strip():
                    continue
                texts.append(value.strip())
                name = simplify(value)
                for key, aliases in HEADER_ALIASES.items():
                    if name in aliases and key not in columns:
                        columns[key] = col
            if columns.keys() >= REQUIRED:
                return Table(ws, row, columns)
            score = len(columns) * 10 + len(texts)
            if texts and (best is None or score > best[0]):
                best = (score, ws.title, row, texts, REQUIRED - columns.keys())

    if best is None:
        message = "Não encontrei nenhum texto de cabeçalho nas primeiras linhas da planilha."
    else:
        _, sheet, row, texts, missing = best
        message = (
            f'Não reconheci a tabela. Na aba "{sheet}", o cabeçalho mais provável (linha {row}) '
            f"tem: {', '.join(texts[:12])}. Faltam colunas de: "
            f"{', '.join(FIELD_LABELS[m] for m in sorted(missing))}."
        )
    logger.info("Planilha não reconhecida: %s", message)  # só cabeçalhos, nenhum valor
    raise SheetFormatError(message)


def _value(table: Table, row: int, key: str) -> Any:
    col = table.columns.get(key)
    return table.ws.cell(row, col).value if col else None


def read_rows(table: Table) -> tuple[list[SheetRow], list[int]]:
    """Linhas válidas e números das linhas ignoradas (total, vazias com valor, inválidas)."""
    rows, skipped = [], []
    for r in range(table.header_row + 1, table.ws.max_row + 1):

        def cell(key: str, r: int = r) -> Any:
            return _value(table, r, key)

        raw_date, raw_value, description = cell("date"), cell("value"), cell("description")
        if raw_date in (None, "") and raw_value in (None, "") and not description:
            continue  # linha vazia
        parsed_date, cents = parse_cell_date(raw_date), parse_cell_amount(raw_value)
        if parsed_date is None or cents is None or not str(description or "").strip():
            skipped.append(r)  # ex.: linha de total ou preenchimento incompleto
            continue
        rows.append(
            SheetRow(
                row=r,
                date=parsed_date,
                counterpart=_text(cell("counterpart")),
                proposal=_text(cell("proposal")),
                description=str(description).strip()[:255],
                entry_type=_text(cell("entry_type")) or "Despesas",
                cents=abs(cents),
            )
        )
    return rows, skipped


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    return text.strip() or None


def match_key(day: date, description: str, cents: int) -> tuple:
    """Como reconhecer que uma linha do sistema já está na planilha."""
    return (day.isoformat(), simplify(description), cents)


# --- importar --------------------------------------------------------------------------------


def import_sheet(db: Session, content: bytes) -> ImportReport:
    table = find_table(_open(content))
    rows, skipped = read_rows(table)
    report = ImportReport(sheet=table.ws.title, skipped=len(skipped), skipped_rows=skipped[:20])

    # Lançamentos feitos no sistema (nota, cupom, manual) que a planilha também pode conter,
    # por exemplo quando ela é o Excel exportado pelo próprio sistema.
    in_system = _system_entries(db)

    seen: Counter[tuple] = Counter()
    created: list[ExpenseItem] = []
    for row in rows:
        signature = (
            row.date.isoformat(), row.counterpart, row.proposal, simplify(row.description),
            row.entry_type, row.cents,
        )  # fmt: skip
        seen[signature] += 1  # duas linhas idênticas continuam sendo duas
        key = hashlib.sha256(repr((*signature, seen[signature])).encode()).hexdigest()
        if db.scalar(select(Expense.id).where(Expense.import_key == key)):
            report.duplicates += 1
            continue
        same = match_key(row.date, row.description, row.cents)
        if in_system[same] > 0:
            in_system[same] -= 1
            report.already_in_system += 1
            continue
        expense = Expense(
            source=ExpenseSource.manual,
            status=ExpenseStatus.confirmed,  # já estava na planilha: foi conferido por alguém
            description=row.description,
            issue_date=row.date,
            total_cents=row.cents,
            proposal=row.proposal,
            entry_type=row.entry_type,
            supplier=upsert_supplier(db, None, row.counterpart),
            import_key=key,
            issues=[],
        )
        item = ExpenseItem(position=1, description=row.description, total_cents=row.cents)
        expense.items = [item]
        db.add(expense)
        created.append(item)
        report.imported += 1

    db.flush()
    # Só regras e memória: o histórico pode ter milhares de linhas, e a LLM na CPU levaria horas.
    categorize_items(db, [i for i in created if i.expense.entry_type != "Receita"], provider=None)
    db.commit()
    logger.info(
        'Planilha importada (aba "%s", cabeçalho na linha %d, colunas %s): %d linha(s) válida(s), '
        "%d nova(s), %d já importada(s), %d já no sistema, %d ignorada(s) %s",
        report.sheet, table.header_row, sorted(table.columns), len(rows), report.imported,
        report.duplicates, report.already_in_system, report.skipped, report.skipped_rows,
    )  # fmt: skip
    return report


def _system_entries(db: Session) -> Counter[tuple]:
    entries: Counter[tuple] = Counter()
    query = select(Expense).where(
        Expense.import_key.is_(None),
        Expense.status.in_([ExpenseStatus.confirmed, ExpenseStatus.needs_review]),
    )
    for expense in db.scalars(query).unique():
        for item in expense.items:
            entries[
                match_key(expense.issue_date or date.min, item.description, item.total_cents)
            ] += 1
    return entries


# --- atualizar a planilha da empresa ---------------------------------------------------------


@dataclass
class UpdateReport:
    content: bytes
    sheet: str
    added: int
    already_in_sheet: int


def update_sheet(db: Session, content: bytes, month: str | None = None) -> UpdateReport:
    workbook = _open(content, keep_vba=False)
    table = find_table(workbook)
    existing_rows, _ = read_rows(table)
    existing = Counter(match_key(r.date, r.description, r.cents) for r in existing_rows)

    query = (
        select(Expense)
        .where(Expense.status == ExpenseStatus.confirmed, Expense.import_key.is_(None))
        .order_by(Expense.issue_date, Expense.id)
    )
    if month:
        start, end = month_range(month)
        query = query.where(Expense.issue_date >= start, Expense.issue_date < end)

    to_add, already = [], 0
    for expense in db.scalars(query).unique():
        for item in expense.items:
            key = match_key(expense.issue_date or date.min, item.description, item.total_cents)
            if existing[key] > 0:
                existing[key] -= 1  # já está na planilha (ex.: lançado à mão antes)
                already += 1
                continue
            to_add.append((expense, item))

    ws, cols = table.ws, table.columns
    # Último lançamento de verdade (não a linha de TOTAL, que pode estar logo abaixo).
    last = max((r.row for r in existing_rows), default=table.header_row)
    if to_add and _has_content_below(ws, last):
        # Insere as linhas antes do total e estende fórmulas como =SOMA(G4:G20) até a nova última.
        ws.insert_rows(last + 1, len(to_add))
        _extend_formula_ranges(
            ws, first_row=last + 1 + len(to_add), old_last=last, new_last=last + len(to_add)
        )
    for offset, (expense, item) in enumerate(to_add, start=1):
        row = last + offset
        values = {
            "date": expense.issue_date,
            "month": expense.issue_date.replace(day=1) if expense.issue_date else None,
            "counterpart": expense.supplier.name if expense.supplier else None,
            "proposal": expense.proposal,
            "description": item.description,
            "entry_type": expense.entry_type,
            "value": item.total_cents / 100,
        }
        for key, col in cols.items():
            target = ws.cell(row, col)
            _copy_style(ws.cell(last, col) if last > table.header_row else None, target)
            target.value = values[key]
            if target.number_format == "General":  # sem formato herdado da linha anterior
                target.number_format = DEFAULT_FORMATS.get(key, "General")

    _extend_excel_tables(ws, old_last=last, new_last=last + len(to_add))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return UpdateReport(buffer.getvalue(), ws.title, len(to_add), already)


def _open(content: bytes, keep_vba: bool = False):
    try:
        return load_workbook(io.BytesIO(content), keep_vba=keep_vba)
    except Exception as exc:
        raise SheetFormatError("Arquivo inválido: envie a planilha em formato .xlsx.") from exc


def _has_content_below(ws: Worksheet, row: int) -> bool:
    return any(
        cell.value not in (None, "")
        for line in ws.iter_rows(min_row=row + 1, max_row=ws.max_row)
        for cell in line
    )


# Intervalo como G4:G20 ou $G$4:$G$20 (captura o fim para poder estender).
_RANGE = re.compile(r"(\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?)(\d+)")


def _extend_formula_ranges(ws: Worksheet, first_row: int, old_last: int, new_last: int) -> None:
    """Nas linhas abaixo dos dados (totais), intervalos que terminavam no último lançamento
    passam a terminar no novo último lançamento."""

    def extend(match: re.Match) -> str:
        end = int(match.group(2))
        return f"{match.group(1)}{new_last if end == old_last else end}"

    for line in ws.iter_rows(min_row=first_row, max_row=ws.max_row):
        for cell in line:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.value = _RANGE.sub(extend, cell.value)


def _copy_style(source, target) -> None:
    if source is None or not source.has_style:
        return
    target.font = copy(source.font)
    target.border = copy(source.border)
    target.fill = copy(source.fill)
    target.alignment = copy(source.alignment)
    target.number_format = source.number_format


def _extend_excel_tables(ws: Worksheet, old_last: int, new_last: int) -> None:
    """Se os dados estão numa "Tabela do Excel", estende o intervalo dela até as linhas novas."""
    for excel_table in ws.tables.values():
        start, end = excel_table.ref.split(":")
        end_col = "".join(ch for ch in end if ch.isalpha())
        end_row = int("".join(ch for ch in end if ch.isdigit()))
        if end_row == old_last and new_last > old_last:
            excel_table.ref = f"{start}:{end_col}{new_last}"
            if excel_table.autoFilter is not None:
                excel_table.autoFilter.ref = excel_table.ref
