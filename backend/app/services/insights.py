"""Alertas de gastos fora do padrão: compara cada categoria do mês com os meses anteriores.

É estatística simples, sem LLM: o número precisa estar certo, e uma regra fixa é fácil de explicar
("62% acima da média dos últimos 3 meses"). A LLM poderia escrever a frase, mas inventaria
valores (veja a checagem de fatos do assistente).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

BASELINE_MONTHS = 3  # meses anteriores usados para a média
MIN_RATIO = 1.5  # alerta a partir de 50% acima da média...
MIN_EXCESS_CENTS = 50_00  # ...e de R$ 50 a mais: R$ 12 contra R$ 8 não é alerta
MIN_NEW_CENTS = 100_00  # categoria sem gasto nos meses anteriores: alerta a partir de R$ 100
MAX_ALERTS = 5


@dataclass(frozen=True)
class CategoryAlert:
    category_id: int
    current_cents: int
    baseline_cents: int  # média mensal nos meses anteriores com movimento (0 = gasto novo)
    baseline_months: int


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def spending_alerts(db: Session, start: date, end: date) -> list[CategoryAlert]:
    """Categorias em que o gasto do mês [start, end) passou muito da média dos meses anteriores.

    A média usa só os meses anteriores **com alguma transação**: quem começou a usar o app no
    mês passado não tem os meses vazios contados como "gastou zero". Sem nenhum mês anterior,
    não há com o que comparar e não há alertas. O mês atual pode estar pela metade; isso só
    deixa o alerta mais conservador, já que o gasto ainda vai crescer.
    """
    current_index = _month_index(start)
    baseline_start = date(
        (current_index - BASELINE_MONTHS) // 12, (current_index - BASELINE_MONTHS) % 12 + 1, 1
    )
    rows = db.execute(
        select(Transaction.date, Transaction.amount_cents, Transaction.category_id).where(
            Transaction.date >= baseline_start, Transaction.date < end
        )
    ).all()

    months_with_data: set[int] = set()
    current: dict[int, int] = defaultdict(int)
    previous: dict[int, int] = defaultdict(int)
    for tx_date, amount, category_id in rows:
        index = _month_index(tx_date)
        if index < current_index:
            months_with_data.add(index)
        if amount >= 0 or category_id is None:  # só despesas com categoria
            continue
        target = current if index == current_index else previous
        target[category_id] += -amount

    if not months_with_data:
        return []
    n = len(months_with_data)

    alerts = []
    for category_id, spent in current.items():
        baseline = round(previous.get(category_id, 0) / n)
        if baseline == 0:
            unusual = spent >= MIN_NEW_CENTS
        else:
            unusual = spent >= baseline * MIN_RATIO and spent - baseline >= MIN_EXCESS_CENTS
        if unusual:
            alerts.append(CategoryAlert(category_id, spent, baseline, n))
    alerts.sort(key=lambda a: a.current_cents - a.baseline_cents, reverse=True)
    return alerts[:MAX_ALERTS]
