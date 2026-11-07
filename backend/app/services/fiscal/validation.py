"""Validações determinísticas que decidem: lançamento automático ou revisão humana.

A regra do sistema é nunca lançar em silêncio um número que não fecha. Se a soma dos itens
não bate com o total, se falta item, se o CNPJ é inválido etc., o documento vai para
"revisar" com a lista dos problemas.
"""

from app.services.fiscal.keys import format_cnpj, is_valid_cnpj

# Tolerância para arredondamento de quantidade × valor unitário (ex.: 2,520 kg × R$ 130,00).
ROUNDING_TOLERANCE_CENTS = 2


def brl(cents: int) -> str:
    value = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}R$ {value}"


def validate(
    *,
    items: list[tuple[float, int | None, int]],  # (quantidade, valor unitário, total) por item
    items_expected_cents: int | None,
    total_cents: int | None,
    declared_item_count: int | None,
    issuer_cnpj: str | None,
    has_issue_date: bool,
    uncategorized: int = 0,
) -> list[str]:
    issues: list[str] = []

    if not items:
        issues.append("Nenhum item foi identificado.")
    if total_cents is None:
        issues.append("Valor total do documento não identificado.")

    expected = items_expected_cents if items_expected_cents is not None else total_cents
    items_sum = sum(total for _, _, total in items)
    if items and expected is not None and items_sum != expected:
        difference = expected - items_sum
        issues.append(
            f"A soma dos itens ({brl(items_sum)}) não bate com o total ({brl(expected)}): "
            f"{'faltam' if difference > 0 else 'sobram'} {brl(abs(difference))}."
        )

    if declared_item_count and items and declared_item_count != len(items):
        issues.append(
            f"O documento informa {declared_item_count} itens, mas {len(items)} foram lidos."
        )

    for position, (quantity, unit_price, total) in enumerate(items, start=1):
        if unit_price is None:
            continue
        if abs(round(quantity * unit_price) - total) > ROUNDING_TOLERANCE_CENTS:
            issues.append(
                f"Item {position}: quantidade × valor unitário "
                f"({quantity:g} × {brl(unit_price)}) não dá o total {brl(total)}."
            )

    if not issuer_cnpj:
        issues.append("CNPJ do fornecedor não identificado.")
    elif not is_valid_cnpj(issuer_cnpj):
        issues.append(f"CNPJ do fornecedor inválido: {format_cnpj(issuer_cnpj)}.")

    if not has_issue_date:
        issues.append("Data de emissão não identificada.")
    if uncategorized:
        issues.append(f"{uncategorized} item(ns) sem categoria.")
    return issues
