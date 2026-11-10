"""Categorização em cascata: memória -> regras -> LLM.

As etapas baratas e determinísticas resolvem a maioria das transações; o LLM só recebe o que
sobrou, em lotes. Cada transação guarda de onde veio a categoria (`categorized_by`), o que
deixa a IA auditável e permite medir a taxa de acerto de cada etapa.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CategorizedBy,
    Category,
    CategoryKind,
    CategoryScope,
    MerchantMemory,
    Transaction,
)
from app.schemas import CategorizationStats
from app.services.categorizer.defaults import CATEGORY_DESCRIPTIONS
from app.services.categorizer.llm import CategoryOption, LLMError, LLMItem, LLMProvider
from app.services.categorizer.rules import match_rule

logger = logging.getLogger(__name__)

RULE_CONFIDENCE = 0.85


@dataclass
class PipelineResult:
    stats: CategorizationStats = field(default_factory=CategorizationStats)
    llm_error: str | None = None


def categorize_transactions(
    db: Session,
    transactions: Sequence[Transaction],
    provider: LLMProvider | None,
    batch_size: int = 10,
) -> PipelineResult:
    result = PipelineResult()
    # O extrato é pessoal: categorias só de empresa não entram nem nas regras nem na LLM.
    categories = [c for c in db.scalars(select(Category)) if c.applies_to(CategoryScope.personal)]
    by_name = {c.name.casefold(): c for c in categories}
    memory = {m.merchant_key: m.category_id for m in db.scalars(select(MerchantMemory))}

    pending: list[Transaction] = []
    for tx in transactions:
        if tx.categorized_by == CategorizedBy.manual:
            continue
        if tx.merchant_key in memory:
            _assign(tx, memory[tx.merchant_key], CategorizedBy.memory, 1.0)
            result.stats.memory += 1
        elif (name := match_rule(tx.description, tx.amount_cents)) and name.casefold() in by_name:
            _assign(tx, by_name[name.casefold()].id, CategorizedBy.rule, RULE_CONFIDENCE)
            result.stats.rule += 1
        else:
            _assign(tx, None, CategorizedBy.none, None)
            pending.append(tx)

    # Agrupa por estabelecimento (e sinal, para separar compras de estornos): três idas à
    # mesma barbearia viram uma única pergunta para a LLM.
    groups: dict[tuple[str, bool], list[Transaction]] = {}
    for tx in pending:
        groups.setdefault((tx.merchant_key, tx.amount_cents > 0), []).append(tx)

    if groups and provider is not None:
        # Reaproveita o que a LLM já decidiu para o mesmo estabelecimento em importações passadas.
        for key, (category_id, confidence) in _previous_llm_decisions(db, groups, pending).items():
            for tx in groups.pop(key):
                _assign(tx, category_id, CategorizedBy.llm, confidence)

        options = [
            CategoryOption(c.name, c.kind.value, CATEGORY_DESCRIPTIONS.get(c.name, ""))
            for c in categories
        ]
        group_list = list(groups.values())
        for start in range(0, len(group_list), batch_size):
            chunk = group_list[start : start + batch_size]
            items = [
                LLMItem(i, members[0].description, members[0].amount_cents)
                for i, members in enumerate(chunk)
            ]
            try:
                suggestions = provider.categorize(items, options)
            except LLMError as exc:
                logger.warning("LLM falhou, seguindo sem ele: %s", exc)
                result.llm_error = str(exc)
                break
            answered: set[int] = set()
            for s in suggestions:
                category = by_name.get(s.category.strip().casefold())
                # Descarta respostas fora da lista, com índice inventado ou repetido.
                if category is None or not 0 <= s.index < len(chunk) or s.index in answered:
                    continue
                # Saída de dinheiro nunca é receita. (Entradas podem ter categoria de despesa:
                # estornos voltam para a categoria da compra original.)
                if chunk[s.index][0].amount_cents < 0 and category.kind == CategoryKind.income:
                    continue
                answered.add(s.index)
                confidence = min(max(s.confidence, 0.0), 1.0)
                for tx in chunk[s.index]:
                    _assign(tx, category.id, CategorizedBy.llm, confidence)

    result.stats.llm = sum(1 for tx in pending if tx.categorized_by == CategorizedBy.llm)
    result.stats.none = sum(1 for tx in pending if tx.categorized_by == CategorizedBy.none)

    db.flush()
    return result


def _previous_llm_decisions(
    db: Session,
    groups: dict[tuple[str, bool], list[Transaction]],
    current: list[Transaction],
) -> dict[tuple[str, bool], tuple[int, float | None]]:
    keys = {merchant for merchant, _ in groups}
    current_ids = [tx.id for tx in current if tx.id is not None]
    rows = db.execute(
        select(
            Transaction.merchant_key,
            Transaction.amount_cents,
            Transaction.category_id,
            Transaction.confidence,
        ).where(
            Transaction.merchant_key.in_(keys),
            Transaction.categorized_by == CategorizedBy.llm,
            Transaction.category_id.is_not(None),
            Transaction.id.not_in(current_ids),
        )
    ).all()
    decisions: dict[tuple[str, bool], tuple[int, float | None]] = {}
    for merchant, amount, category_id, confidence in rows:
        key = (merchant, amount > 0)
        if key in groups:
            decisions.setdefault(key, (category_id, confidence))
    return decisions


def remember(db: Session, merchant_key: str, category_id: int) -> None:
    """Grava a correção do usuário para as próximas importações."""
    entry = db.scalar(select(MerchantMemory).where(MerchantMemory.merchant_key == merchant_key))
    if entry is None:
        db.add(MerchantMemory(merchant_key=merchant_key, category_id=category_id, hits=1))
    else:
        entry.category_id = category_id
        entry.hits += 1


def _assign(
    tx: Transaction, category_id: int | None, source: CategorizedBy, confidence: float | None
) -> None:
    tx.category_id = category_id
    tx.categorized_by = source
    tx.confidence = confidence
