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

from app.models import CategorizedBy, Category, MerchantMemory, Transaction
from app.schemas import CategorizationStats
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
    batch_size: int = 25,
) -> PipelineResult:
    result = PipelineResult()
    categories = list(db.scalars(select(Category)))
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

    if pending and provider is not None:
        options = [CategoryOption(c.name, c.kind.value) for c in categories]
        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]
            items = [LLMItem(i, tx.description, tx.amount_cents) for i, tx in enumerate(chunk)]
            try:
                suggestions = provider.categorize(items, options)
            except LLMError as exc:
                logger.warning("LLM falhou, seguindo sem ele: %s", exc)
                result.llm_error = str(exc)
                break
            for s in suggestions:
                category = by_name.get(s.category.strip().casefold())
                # Descarta respostas fora da lista ou com índice inventado.
                if category is None or not 0 <= s.index < len(chunk):
                    continue
                tx = chunk[s.index]
                if tx.categorized_by == CategorizedBy.llm:
                    continue  # índice repetido na resposta
                _assign(tx, category.id, CategorizedBy.llm, min(max(s.confidence, 0.0), 1.0))
                result.stats.llm += 1

    result.stats.none = sum(1 for tx in pending if tx.categorized_by == CategorizedBy.none)

    db.flush()
    return result


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
