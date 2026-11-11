from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Transaction
from app.schemas import (
    CategorizationStats,
    CategoryTotal,
    DashboardSummary,
    MonthTotal,
    SpendingAlert,
)
from app.services.insights import spending_alerts

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def month_range(month: str) -> tuple[date, date]:
    """'2026-10' -> (2026-10-01, 2026-11-01)."""
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start, end


def shift_month(month: str, delta: int) -> str:
    year, mon = map(int, month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@router.get("/summary", response_model=DashboardSummary)
def summary(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    months_back: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
):
    if month is None:
        latest = db.scalar(select(func.max(Transaction.date)))
        month = (latest or date.today()).strftime("%Y-%m")
    start, end = month_range(month)

    rows = db.execute(
        select(Transaction.amount_cents, Transaction.category_id, Transaction.categorized_by).where(
            Transaction.date >= start, Transaction.date < end
        )
    ).all()

    income = sum(a for a, _, _ in rows if a > 0)
    expense = -sum(a for a, _, _ in rows if a < 0)

    expense_by_cat: dict[int | None, int] = defaultdict(int)
    stats = CategorizationStats()
    for amount, category_id, source in rows:
        if amount < 0:
            expense_by_cat[category_id] += -amount
        if source.value != "manual":
            setattr(stats, source.value, getattr(stats, source.value) + 1)

    categories = {c.id: c for c in db.scalars(select(Category))}
    by_category = [
        CategoryTotal(
            category_id=cid,
            name=categories[cid].name if cid in categories else "Sem categoria",
            color=categories[cid].color if cid in categories else "#cbd5e1",
            icon=categories[cid].icon if cid in categories else "❔",
            total_cents=total,
        )
        for cid, total in expense_by_cat.items()
    ]
    by_category.sort(key=lambda c: c.total_cents, reverse=True)

    first_month = shift_month(month, -(months_back - 1))
    series_start, _ = month_range(first_month)
    series_rows = db.execute(
        select(Transaction.date, Transaction.amount_cents).where(
            Transaction.date >= series_start, Transaction.date < end
        )
    ).all()
    buckets = {shift_month(first_month, i): [0, 0] for i in range(months_back)}
    for tx_date, amount in series_rows:
        bucket = buckets[tx_date.strftime("%Y-%m")]
        if amount > 0:
            bucket[0] += amount
        else:
            bucket[1] += -amount

    return DashboardSummary(
        month=month,
        income_cents=income,
        expense_cents=expense,
        balance_cents=income - expense,
        transaction_count=len(rows),
        expenses_by_category=by_category,
        monthly=[
            MonthTotal(month=m, income_cents=i, expense_cents=e) for m, (i, e) in buckets.items()
        ],
        categorized_by=stats,
        alerts=[
            SpendingAlert(
                category_id=a.category_id,
                name=categories[a.category_id].name,
                color=categories[a.category_id].color,
                icon=categories[a.category_id].icon,
                current_cents=a.current_cents,
                baseline_cents=a.baseline_cents,
                baseline_months=a.baseline_months,
            )
            for a in spending_alerts(db, start, end)
            if a.category_id in categories
        ],
    )
