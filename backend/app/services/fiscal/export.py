"""Exporta os lançamentos para Excel: é o que substitui a planilha preenchida à mão.

A primeira aba segue exatamente as colunas da planilha da empresa:
Data | Mês | Cliente/Fornecedor | Proposta | Descrição | Tipo | Valor (R$), uma linha por item.
"""

import io
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.models import Expense, ExpenseSource, ExpenseStatus
from app.services.fiscal.entry_types import INCOME_TYPES
from app.services.fiscal.keys import format_cnpj

if TYPE_CHECKING:
    from app.schemas import ItemRow

MONEY = "#,##0.00"
DATE = "DD/MM/YYYY"
MONTH = "MMM/YY"  # data do 1º dia do mês, exibida como "nov/26": filtra e ordena no Excel
HEADER_FILL = PatternFill("solid", fgColor="065F46")
NO_PROPOSAL = "(sem proposta)"

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
    ws: Worksheet,
    headers: list[str],
    rows: list[list],
    formats: dict[int, str] | None = None,
) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for row in rows:
        ws.append(row)
    for col in range(1, len(headers) + 1):
        letter = get_column_letter(col)
        if formats and col in formats:
            for cell in ws[letter][1:]:
                cell.number_format = formats[col]
        width = max(len(str(c.value or "")) for c in ws[letter])
        ws.column_dimensions[letter].width = min(max(12, width + 2), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


PLANILHA_HEADERS = [
    "Data", "Mês", "Cliente/Fornecedor", "Proposta", "Descrição", "Tipo", "Valor (R$)",
]  # fmt: skip


def build_items_workbook(rows: Sequence["ItemRow"]) -> bytes:
    """Só a aba no formato da planilha, com os itens filtrados e uma linha de total."""
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Planilha"
    data = [
        [
            r.issue_date,
            r.issue_date.replace(day=1) if r.issue_date else None,
            r.counterpart or "",
            r.proposal or "",
            r.description,
            r.entry_type,
            r.total_cents / 100,
        ]
        for r in rows
    ]
    _sheet(sheet, PLANILHA_HEADERS, data, {1: DATE, 2: MONTH, 7: MONEY})
    sheet.append([])
    sheet.append(
        [
            "Total",
            None,
            None,
            None,
            f"{len(rows)} itens",
            None,
            sum(r.total_cents for r in rows) / 100,
        ]
    )
    total_row = sheet.max_row
    for cell in sheet[total_row]:
        cell.font = Font(bold=True)
    sheet.cell(total_row, 7).number_format = MONEY
    sheet.auto_filter.ref = f"A1:G{len(rows) + 1}"  # o filtro não inclui a linha de total
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _counterpart(e: Expense) -> str:
    return e.supplier.name if e.supplier else ""


def build_workbook(expenses: Sequence[Expense]) -> bytes:
    wb = Workbook()
    expenses = sorted(expenses, key=lambda e: (e.issue_date or date.min, e.id))

    # 1. Formato da planilha da empresa: uma linha por item
    rows = []
    for e in expenses:
        month = e.issue_date.replace(day=1) if e.issue_date else None
        for item in e.items:
            rows.append(
                [
                    e.issue_date,
                    month,
                    _counterpart(e),
                    e.proposal or "",
                    item.description,
                    e.entry_type,
                    item.total_cents / 100,
                ]
            )
    sheet = wb.active
    sheet.title = "Planilha"
    _sheet(
        sheet,
        PLANILHA_HEADERS,
        rows,
        {1: DATE, 2: MONTH, 7: MONEY},
    )

    # 2. Resultado por proposta/obra: receitas - custos
    by_proposal: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in expenses:
        by_proposal[e.proposal or NO_PROPOSAL][e.entry_type] += e.total_cents or 0
    proposal_rows = []
    for proposal, totals in sorted(by_proposal.items(), key=lambda kv: kv[0] == NO_PROPOSAL):
        income = sum(v for k, v in totals.items() if k in INCOME_TYPES)
        spent = sum(v for k, v in totals.items() if k not in INCOME_TYPES)
        proposal_rows.append(
            [
                proposal,
                income / 100,
                totals.get("Custo", 0) / 100,
                (spent - totals.get("Custo", 0)) / 100,
                (income - spent) / 100,
            ]
        )
    _sheet(
        wb.create_sheet("Por proposta"),
        ["Proposta", "Receitas", "Custos", "Outras saídas", "Resultado"],
        proposal_rows,
        {2: MONEY, 3: MONEY, 4: MONEY, 5: MONEY},
    )

    # 3. Totais por categoria e tipo
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for e in expenses:
        for item in e.items:
            category = item.category.name if item.category else "Sem categoria"
            totals[(e.entry_type, category)] += item.total_cents
    _sheet(
        wb.create_sheet("Por categoria"),
        ["Tipo", "Categoria", "Total"],
        [[t, c, v / 100] for (t, c), v in sorted(totals.items(), key=lambda kv: -kv[1])],
        {3: MONEY},
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
        {2: MONEY},
    )

    # 5. Uma linha por documento, com os dados fiscais (para conferência)
    _sheet(
        wb.create_sheet("Notas"),
        [
            "ID",
            "Data",
            "Cliente/Fornecedor",
            "CNPJ",
            "Nº nota",
            "Proposta",
            "Tipo",
            "Funcionário",
            "Reembolsar",
            "Pagamento",
            "Valor total",
            "Status",
            "Origem",
            "Chave de acesso",
        ],
        [
            [
                e.id,
                e.issue_date,
                _counterpart(e),
                format_cnpj(e.supplier.cnpj) if e.supplier and e.supplier.cnpj else "",
                e.number or "",
                e.proposal or "",
                e.entry_type,
                e.employee.name if e.employee else "",
                "Sim" if e.reimbursable else "Não",
                e.payment_method or "",
                (e.total_cents or 0) / 100,
                STATUS_LABELS[e.status],
                SOURCE_LABELS[e.source],
                e.access_key or "",
            ]
            for e in expenses
        ],
        {2: DATE, 11: MONEY},
    )

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
