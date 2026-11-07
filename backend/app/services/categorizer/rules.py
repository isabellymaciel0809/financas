from app.services.categorizer.defaults import EXPENSE_RULES, INCOME_RULES
from app.services.text import contains_phrase, simplify


def match_rule(description: str, amount_cents: int) -> str | None:
    """Retorna o nome da categoria cuja palavra-chave aparece na descrição.

    Usa o sinal do valor: regras de receita só valem para entradas e vice-versa.
    Em caso de várias correspondências, vence a frase mais longa (mais específica).
    """
    rules = INCOME_RULES if amount_cents > 0 else EXPENSE_RULES
    text = simplify(description)
    best: tuple[int, str] | None = None
    for category, phrases in rules.items():
        for phrase in phrases:
            if contains_phrase(text, phrase) and (best is None or len(phrase) > best[0]):
                best = (len(phrase), category)
    return best[1] if best else None
