"""Exporta os lançamentos para Excel: é o que substitui a planilha preenchida à mão."""

import io
from collections import defaultdict
from collections.abc import Sequence

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.models import Expense, ExpenseSource, ExpenseStatus
from app.services.fiscal.keys import format_cnpj

MONEY = "R$ #,##0.00;[Red]-R$ #,##0.00"
DATE = "DD/MM/YYYY"
HEADER_FILL = PatternFill("solid", fgColor="065F46")

STATUS_LABELS = {
    ExpenseStatus.processing: "Processando",
    ExpenseStatus.needs_review: "Revisar",
    ExpenseStatus.confirmed: "Confirmado",
    ExpenseStatus.duplicate: "Duplicado",
    ExpenseStatus.error: "Erro",
}
SOURCE_LABELS = {
    ExpenseSource.nfe_xml: "XML NF-e",
    ExpenseSource.photo: "Foto de cupom",
    ExpenseSource.manual: "Manual",
}


def _sheet(
    ws: Worksheet, headers: list[str], rows: list[list], money_cols: set[int], date_cols: set[int]
) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for row in rows:
        ws.append(row)
    for col in range(1, len(headers) + 1):
        letter = get_column_letter(col)
        if col in money_cols or col in date_cols:
            for cell in ws[letter][1:]:
                cell.number_format = MONEY if col in money_cols else DATE
        width = max(len(str(c.value or "")) for c in ws[letter])
        ws.column_dimensions[letter].width = min(max(12, width + 2), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _reais(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


def build_workbook(expenses: Sequence[Expense]) -> bytes:
    wb = Workbook()

    # 1. Um lançamento por linha
    rows = []
    for e in expenses:
        by_category: dict[str, int] = defaultdict(int)
        for item in e.items:
            by_category[item.category.name if item.category else "Sem categoria"] += (
                item.total_cents
            )
        main_category = max(by_category, key=by_category.get) if by_category else ""
        rows.append(
            [
                e.id,
                e.issue_date,
                e.supplier.name if e.supplier else "",
                format_cnpj(e.supplier.cnpj) if e.supplier and e.supplier.cnpj else "",
                e.number or "",
                e.description or "",
                main_category,
                e.employee.name if e.employee else "",
                "Sim" if e.reimbursable else "Não",
                e.payment_method or "",
                _reais(e.total_cents),
                STATUS_LABELS[e.status],
                SOURCE_LABELS[e.source],
                e.access_key or "",
            ]
        )
    _sheet(
        wb.active,
        [
            "ID",
            "Data",
            "Fornecedor",
            "CNPJ",
            "Nº nota",
            "Descrição",
            "Categoria principal",
            "Funcionário",
            "Reembolsar",
            "Pagamento",
            "Valor total",
            "Status",
            "Origem",
            "Chave de acesso",
        ],
        rows,
        money_cols={11},
        date_cols={2},
    )
    wb.active.title = "Lançamentos"

    # 2. Um item por linha (para tabelas dinâmicas)
    item_rows = [
        [
            e.id,
            e.issue_date,
            e.supplier.name if e.supplier else "",
            item.description,
            item.quantity,
            item.unit or "",
            _reais(item.unit_price_cents),
            _reais(item.total_cents),
            item.category.name if item.category else "Sem categoria",
            e.employee.name if e.employee else "",
        ]
        for e in expenses
        for item in e.items
    ]
    _sheet(
        wb.create_sheet("Itens"),
        [
            "Lançamento",
            "Data",
            "Fornecedor",
            "Item",
            "Qtd",
            "Un",
            "Valor unitário",
            "Valor total",
            "Categoria",
            "Funcionário",
        ],
        item_rows,
        money_cols={7, 8},
        date_cols={2},
    )

    # 3. Totais por categoria
    totals: dict[str, int] = defaultdict(int)
    for e in expenses:
        for item in e.items:
            totals[item.category.name if item.category else "Sem categoria"] += item.total_cents
    _sheet(
        wb.create_sheet("Por categoria"),
        ["Categoria", "Total"],
        [[name, cents / 100] for name, cents in sorted(totals.items(), key=lambda kv: -kv[1])],
        money_cols={2},
        date_cols=set(),
    )

    # 4. Quanto devolver a cada funcionário
    refunds: dict[str, int] = defaultdict(int)
    for e in expenses:
        if e.reimbursable and e.employee and e.status == ExpenseStatus.confirmed:
            refunds[e.employee.name] += e.total_cents or 0
    _sheet(
        wb.create_sheet("Reembolsos"),
        ["Funcionário", "A reembolsar"],
        [[name, cents / 100] for name, cents in sorted(refunds.items())],
        money_cols={2},
        date_cols=set(),
    )

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
