import re

from app.services.categorizer.defaults import EXPENSE_RULES, INCOME_RULES
from app.services.text import contains_phrase, simplify

# Intermediadores de pagamento: dizem quem processou a compra, não onde ela foi feita.
# "MERCADO PAGO *LOJA X" não é supermercado, então o prefixo é removido antes das regras.
PAYMENT_PROCESSORS = ["mercado pago", "mercadopago", "pagseguro", "sumup", "stone"]

_OCR_DIGITS = str.maketrans({"0": "o", "1": "i", "5": "s"})


def _ocr_tokens(text: str) -> list[str]:
    """Palavras corrigidas para erros típicos de OCR em cupons.

    "TUB0" -> "tubo", "2UNIAOC/VALVULA" -> "uniaoc", "FITAPUC10LINEAR" -> "fitapuciolinear".
    Só toca em palavras com pelo menos 3 letras, para não estragar números e medidas.
    """
    tokens = []
    for token in text.split():
        token = token.lstrip("0123456789")
        if sum(ch.isalpha() for ch in token) >= 3:
            tokens.append(token.translate(_OCR_DIGITS))
    return tokens


def match_rule(description: str, amount_cents: int, ocr_tolerant: bool = False) -> str | None:
    """Retorna o nome da categoria cuja palavra-chave aparece na descrição.

    Usa o sinal do valor: regras de receita só valem para entradas e vice-versa.
    Em caso de várias correspondências, vence a frase mais longa (mais específica).

    `ocr_tolerant`: para itens lidos de foto, aceita a palavra-chave no começo de uma palavra
    grudada ("FITAPUC10LINEAR" casa com "fita") e corrige 0/1/5 trocados por O/I/S.
    """
    rules = INCOME_RULES if amount_cents > 0 else EXPENSE_RULES
    text = f" {simplify(description)} "
    for processor in PAYMENT_PROCESSORS:
        text = text.replace(f" {processor} ", " ")
    text = text.strip()
    tokens = _ocr_tokens(re.sub(r"[^a-z0-9 ]", " ", text)) if ocr_tolerant else []

    best: tuple[int, str] | None = None
    for category, phrases in rules.items():
        for phrase in phrases:
            found = contains_phrase(text, phrase) or (
                len(phrase) >= 4 and " " not in phrase and any(t.startswith(phrase) for t in tokens)
            )
            if found and (best is None or len(phrase) > best[0]):
                best = (len(phrase), category)
    return best[1] if best else None
