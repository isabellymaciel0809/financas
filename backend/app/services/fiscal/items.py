"""Categorização dos itens de um lançamento: memória -> regras -> LLM (mesma cascata do extrato)."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategorizedBy, Category, CategoryKind, ExpenseItem, MerchantMemory
from app.services.categorizer.defaults import CATEGORY_DESCRIPTIONS
from app.services.categorizer.llm import CategoryOption, LLMError, LLMItem, LLMProvider
from app.services.categorizer.pipeline import RULE_CONFIDENCE
from app.services.categorizer.rules import match_rule
from app.services.fiscal.receipt_parser import ILLEGIBLE
from app.services.text import merchant_key

logger = logging.getLogger(__name__)


def categorize_items(
    db: Session,
    items: list[ExpenseItem],
    provider: LLMProvider | None,
    batch_size: int = 10,
    supplier: str | None = None,
    from_ocr: bool = False,
) -> str | None:
    """Categoriza os itens ainda sem categoria. Devolve o erro do LLM, se houver.

    `supplier` e `from_ocr` dão contexto à LLM: "HANOMETRO" sozinho não diz nada, mas
    "item de OCR comprado na FRIGELAR" leva a "manômetro" (ferramenta de refrigeração).
    """
    categories = [c for c in db.scalars(select(Category)) if c.kind == CategoryKind.expense]
    by_name = {c.name.casefold(): c for c in categories}
    memory = {m.merchant_key: m.category_id for m in db.scalars(select(MerchantMemory))}

    groups: dict[str, list[ExpenseItem]] = {}
    for item in items:
        if item.categorized_by == CategorizedBy.manual or item.category_id is not None:
            continue
        if item.description == ILLEGIBLE:
            continue  # sem texto, a IA só chutaria: fica para a revisão humana
        key = merchant_key(item.description)
        rule = match_rule(item.description, -abs(item.total_cents), ocr_tolerant=True)
        if key in memory:
            _set(item, memory[key], CategorizedBy.memory, 1.0)
        elif rule and rule.casefold() in by_name:
            _set(item, by_name[rule.casefold()].id, CategorizedBy.rule, RULE_CONFIDENCE)
        else:
            groups.setdefault(key, []).append(item)

    if not groups or provider is None or not provider.is_available():
        return None

    options = [
        CategoryOption(c.name, c.kind.value, CATEGORY_DESCRIPTIONS.get(c.name, ""))
        for c in categories
    ]
    group_list = list(groups.values())
    for start in range(0, len(group_list), batch_size):
        chunk = group_list[start : start + batch_size]
        llm_items = [
            LLMItem(
                i,
                _with_context(members[0].description, supplier, from_ocr),
                -abs(members[0].total_cents),
            )
            for i, members in enumerate(chunk)
        ]
        try:
            suggestions = provider.categorize(llm_items, options)
        except LLMError as exc:
            logger.warning("LLM falhou ao categorizar itens: %s", exc)
            return str(exc)
        answered: set[int] = set()
        for s in suggestions:
            category = by_name.get(s.category.strip().casefold())
            if category is None or not 0 <= s.index < len(chunk) or s.index in answered:
                continue
            answered.add(s.index)
            for item in chunk[s.index]:
                _set(item, category.id, CategorizedBy.llm, min(max(s.confidence, 0.0), 1.0))
    return None


def _with_context(description: str, supplier: str | None, from_ocr: bool) -> str:
    context = []
    if supplier:
        context.append(f"item comprado em {supplier}")
    if from_ocr:
        context.append("texto lido por OCR, pode ter letras trocadas como H/M, 0/O, U/V")
    return f"{description} ({'; '.join(context)})" if context else description


def _set(item: ExpenseItem, category_id: int, source: CategorizedBy, confidence: float) -> None:
    item.category_id = category_id
    item.categorized_by = source
    item.confidence = confidence
