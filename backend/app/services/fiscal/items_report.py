"""Consulta de itens de todas as notas, como numa planilha: filtros + totais.

Responde perguntas como "quanto gastei de tubo de cobre este mês?", "quais materiais foram
para a proposta P-123?" e "quanto foi Custo × Despesas em novembro?".
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseItem, ExpenseStatus, Supplier
from app.routers.dashboard import month_range
from app.schemas import CategoryOut, GroupTotal, ItemRow, ItemsReport

MAX_ROWS = 1000
UNCATEGORIZED = "Sem categoria"


@dataclass
class ItemFilters:
    month: str | None = None
    proposal: str | None = None
    entry_type: str | None = None
    category_id: int | None = None
    search: str | None = None
    only_confirmed: bool = False


def query_items(db: Session, filters: ItemFilters) -> list[tuple[ExpenseItem, Expense]]:
    # Itens em revisão entram (com aviso na tela); duplicados, erros e fila, não.
    statuses = [ExpenseStatus.confirmed]
    if not filters.only_confirmed:
        statuses.append(ExpenseStatus.needs_review)

    query = (
        select(ExpenseItem, Expense)
        .join(ExpenseItem.expense)
        .outerjoin(Supplier, Expense.supplier_id == Supplier.id)
        .where(Expense.status.in_(statuses))
    )
    if filters.month:
        start, end = month_range(filters.month)
        query = query.where(Expense.issue_date >= start, Expense.issue_date < end)
    if filters.proposal:
        query = query.where(Expense.proposal == filters.proposal)
    if filters.entry_type:
        query = query.where(Expense.entry_type == filters.entry_type)
    if filters.category_id is not None:
        query = query.where(ExpenseItem.category_id == filters.category_id)
    if filters.search:
        pattern = f"%{filters.search.strip()}%"
        query = query.where(
            or_(ExpenseItem.description.ilike(pattern), Supplier.name.ilike(pattern))
        )
    query = query.order_by(Expense.issue_date.desc(), Expense.id.desc(), ExpenseItem.position)
    return [(item, expense) for item, expense in db.execute(query).unique()]


def to_row(item: ExpenseItem, expense: Expense) -> ItemRow:
    return ItemRow(
        id=item.id,
        expense_id=expense.id,
        expense_status=expense.status,
        issue_date=expense.issue_date,
        counterpart=expense.supplier.name if expense.supplier else None,
        proposal=expense.proposal,
        description=item.description,
        entry_type=expense.entry_type,
        category=CategoryOut.model_validate(item.category) if item.category else None,
        quantity=item.quantity,
        unit=item.unit,
        unit_price_cents=item.unit_price_cents,
        total_cents=item.total_cents,
    )


def _grouped(pairs: list[tuple[str, int]]) -> list[GroupTotal]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for name, cents in pairs:
        totals[name][0] += cents
        totals[name][1] += 1
    return [
        GroupTotal(name=name, total_cents=total, count=count)
        for name, (total, count) in sorted(totals.items(), key=lambda kv: -kv[1][0])
    ]


def build_report(db: Session, filters: ItemFilters) -> ItemsReport:
    rows = query_items(db, filters)
    return ItemsReport(
        items=[to_row(item, expense) for item, expense in rows[:MAX_ROWS]],
        count=len(rows),
        total_cents=sum(item.total_cents for item, _ in rows),
        by_type=_grouped([(expense.entry_type, item.total_cents) for item, expense in rows]),
        by_category=_grouped(
            [
                (item.category.name if item.category else UNCATEGORIZED, item.total_cents)
                for item, _ in rows
            ]
        ),
        truncated=len(rows) > MAX_ROWS,
    )
