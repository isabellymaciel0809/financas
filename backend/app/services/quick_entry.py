"""Lançamento por texto: "gastei 45 no mercado ontem" vira uma transação.

Mesma cascata do resto do app: um leitor por padrões entende as frases comuns na hora, sem
custo; a LLM só entra quando ele não entende (valor por extenso, dois números na frase...). O
que a LLM devolve é validado pelo backend, e nada é salvo sem o usuário ver a prévia.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, CategoryScope, MerchantMemory
from app.services.categorizer.llm import LLMError, LLMProvider
from app.services.categorizer.rules import match_rule
from app.services.text import merchant_key

MAX_CENTS = 10_000_000_00  # R$ 10 milhões: acima disso, é erro de digitação ou de leitura

WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
INCOME_WORDS = r"recebi|ganhei|entrou|entraram|caiu|vendi|recebido|salario|reembolso|rendimento"
EXPENSE_WORDS = r"gastei|paguei|comprei|torrei|gasto|gastos|compra|pagamento|foi|foram|deu|saiu"
# Palavras que sobram nas pontas da descrição ("no mercado" -> "mercado").
EDGE_WORDS = {
    "no", "na", "nos", "nas", "em", "de", "do", "da", "dos", "das", "com", "pra", "para", "pro",
    "por", "um", "uma", "o", "a", "os", "as", "e", "reais", "real", "conto", "contos", "pila",
    "r$", "mil", "hoje", "ontem", "anteontem", "dia", "passada", "passado", "ultima", "ultimo",
}  # fmt: skip

_NUMBER = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY = re.compile(
    rf"(?P<prefix>r\$\s*)?(?P<number>{_NUMBER})(?P<mil>\s*mil\b)?"
    rf"(?P<suffix>\s*(?:reais|real|contos?|pila)\b)?"
)
_FULL_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b")
_DAY_OF_MONTH = re.compile(r"\b(?:no\s+)?dia\s+(\d{1,2})\b")


class NotUnderstood(ValueError):
    """O texto não virou um lançamento: a mensagem diz o que tentar."""


@dataclass
class ParsedEntry:
    date: date
    description: str
    amount_cents: int  # negativo = despesa
    understood_by: str  # "regras" ou "ia"
    warnings: list[str] = field(default_factory=list)


def _plain(text: str) -> str:
    """Minúsculas e sem acento, com o mesmo tamanho do original (as posições batem)."""
    out = []
    for ch in text.lower():
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def _to_cents(number: str, thousands: bool = False) -> int:
    if "," in number:
        value = float(number.replace(".", "").replace(",", "."))
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", number):
        value = float(number.replace(".", ""))  # 1.200 = mil e duzentos
    else:
        value = float(number)
    return round(value * (1000 if thousands else 1) * 100)


def _months_back(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _find_date(plain: str, today: date) -> tuple[date, list[tuple[int, int]]]:
    """Data citada no texto (ou hoje) e os trechos que a mencionam, para tirar da descrição."""
    if m := re.search(r"\banteontem\b", plain):
        return today - timedelta(days=2), [m.span()]
    if m := re.search(r"\bontem\b", plain):
        return today - timedelta(days=1), [m.span()]
    if m := _FULL_DATE.search(plain):
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else today.year
        year += 2000 if year < 100 else 0
        try:
            found = date(year, month, day)
        except ValueError as exc:
            raise NotUnderstood(f"A data {m[0]} não existe.") from exc
        if found > today and not m[3]:
            found = found.replace(year=year - 1)  # "20/12" dito em janeiro: dezembro passado
        return found, [m.span()]
    if m := _DAY_OF_MONTH.search(plain):
        day = int(m[1])
        month_start = today.replace(day=1)
        if day > today.day:
            month_start = _months_back(month_start, 1)  # "dia 28" dito no dia 3: mês passado
        try:
            return month_start.replace(day=day), [m.span()]
        except ValueError as exc:
            raise NotUnderstood(f"O dia {day} não existe nesse mês.") from exc
    for name, weekday in WEEKDAYS.items():
        if m := re.search(rf"\b(?:n[oa]\s+)?{name}(?:-feira)?(\s+passad[oa])?\b", plain):
            back = (today.weekday() - weekday) % 7
            if back == 0 and m[1]:
                back = 7
            return today - timedelta(days=back), [m.span()]
    if m := re.search(r"\bhoje\b", plain):
        return today, [m.span()]
    return today, []


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _clean_description(original: str, plain: str) -> str:
    """Tira verbos e palavras soltas das pontas: "gastei  no mercado" -> "Mercado"."""
    spans = [m.span() for m in re.finditer(rf"\b(?:{INCOME_WORDS}|{EXPENSE_WORDS})\b", plain)]
    words = _blank(original, spans).split()
    plain_words = _blank(plain, spans).split()
    while plain_words and plain_words[0].strip(".,!") in EDGE_WORDS:
        words.pop(0), plain_words.pop(0)
    while plain_words and plain_words[-1].strip(".,!") in EDGE_WORDS:
        words.pop(), plain_words.pop()
    description = " ".join(words).strip(" .,!")
    return description[:1].upper() + description[1:]


def _is_income(plain: str) -> bool:
    return re.search(rf"\b(?:{INCOME_WORDS})\b", plain) is not None


def parse_with_rules(text: str, today: date) -> ParsedEntry | None:
    """Leitor por padrões. Devolve None quando não tem certeza (aí a LLM tenta)."""
    plain = _plain(text)
    when, date_spans = _find_date(plain, today)
    without_date = _blank(plain, date_spans)

    amounts = list(_MONEY.finditer(without_date))
    marked = [m for m in amounts if m["prefix"] or m["suffix"] or m["mil"]]
    if len(marked) == 1:
        money = marked[0]
    elif len(amounts) == 1:
        money = amounts[0]
    else:
        return None  # sem número ou com vários sem "R$"/"reais" ("2 pizzas por 80"): ambíguo
    cents = _to_cents(money["number"], thousands=bool(money["mil"]))

    spans = [*date_spans, money.span()]
    description = _clean_description(_blank(text, spans), _blank(plain, spans))
    if not description or cents <= 0:
        return None
    warnings = []
    if len(amounts) > 1:  # "3 cafés de 7 reais": 7 ou 21?
        warnings.append("Havia outros números no texto: confira o valor.")
    return ParsedEntry(
        when, description, cents if _is_income(plain) else -cents, "regras", warnings
    )


# Palavras de número e de dinheiro: saem da descrição que a LLM devolve ("trinta conto no bar").
NUMBER_WORDS = {
    "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove",
    "dez", "onze", "doze", "treze", "quatorze", "catorze", "quinze", "dezesseis", "dezessete",
    "dezoito", "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
    "oitenta", "noventa", "cem", "cento", "duzentos", "trezentos", "quatrocentos",
    "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos", "mil", "reais",
    "real", "conto", "contos", "pila", "centavos",
}  # fmt: skip

# A LLM só faz o que as regras não conseguem: ler o valor por extenso e separar a descrição.
# Data e tipo (despesa ou receita) ficam com o backend: testado com o qwen2.5:3b, ele marcou
# "netflix vinte e cinco" como receita e ignorou o "sexta" de "no bar sexta".
LLM_SYSTEM = (
    "Você lê uma frase em português do Brasil sobre um gasto ou um recebimento. "
    'valor: o valor em reais, como número ("cinquenta e dois e noventa" = 52.9). '
    "descricao: onde ou com o que foi, usando só palavras da frase, sem o valor e sem a data."
)
LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"valor": {"type": "number"}, "descricao": {"type": "string"}},
    "required": ["valor", "descricao"],
}


def _grounded_description(description: str, plain_text: str) -> str:
    """Só as palavras da LLM que estão na frase: "Vendendo trinta contos no bar" -> "Bar"."""
    in_text = set(re.findall(r"[a-z0-9]+", plain_text))
    verbs = re.compile(rf"(?:{INCOME_WORDS}|{EXPENSE_WORDS})")
    kept = [
        word
        for word in description.split()
        if (p := _plain(word).strip(".,!")) in in_text
        and p not in NUMBER_WORDS
        and not verbs.fullmatch(p)
    ]
    joined = " ".join(kept)
    return _clean_description(joined, _plain(joined))


def parse_with_llm(text: str, today: date, provider: LLMProvider) -> ParsedEntry:
    """A LLM só lê o valor e a descrição; o backend confere os dois e decide o resto."""
    plain = _plain(text)
    when, date_spans = _find_date(plain, today)
    without_date = _blank(plain, date_spans)
    try:
        raw = provider.extract_json(LLM_SYSTEM, text, LLM_SCHEMA)
    except LLMError as exc:
        raise NotUnderstood(f"A IA não respondeu ({exc}).") from exc

    warnings: list[str] = []
    try:
        cents = round(float(raw["valor"]) * 100)
    except (KeyError, TypeError, ValueError) as exc:
        raise NotUnderstood("Não encontrei o valor.") from exc
    if not 0 < cents <= MAX_CENTS:
        raise NotUnderstood("Não encontrei o valor.")
    # Checagem de fatos, como no assistente: com números no texto, o valor tem que ser um deles.
    written = {_to_cents(m["number"], bool(m["mil"])) for m in _MONEY.finditer(without_date)}
    if written and cents not in written:
        raise NotUnderstood("Não tenho certeza do valor. Escreva só o valor, como em 'gastei 45'.")
    if not written:
        warnings.append("O valor foi escrito por extenso: confira.")

    description = _grounded_description(str(raw.get("descricao", ""))[:120], without_date)
    if not description:
        raise NotUnderstood("Não entendi onde ou com o que foi.")
    sign = 1 if _is_income(plain) else -1
    return ParsedEntry(when, description, sign * cents, "ia", warnings)


def parse_entry(text: str, today: date, provider: LLMProvider | None) -> ParsedEntry:
    text = " ".join(text.split())
    entry = parse_with_rules(text, today)
    if entry is None:
        if provider is None or not provider.is_available():
            raise NotUnderstood(
                "Não entendi. Escreva o valor em números, como em 'gastei 45 no mercado ontem'."
            )
        entry = parse_with_llm(text, today, provider)
    if entry.date > today:
        raise NotUnderstood(f"A data {entry.date:%d/%m/%Y} ainda não chegou.")
    return entry


def suggest_category(
    db: Session, description: str, amount_cents: int
) -> tuple[Category, str] | None:
    """Categoria que a cascata daria agora, sem a LLM: memória das correções ou regras."""
    key = merchant_key(description)
    remembered = db.scalar(select(MerchantMemory).where(MerchantMemory.merchant_key == key))
    if remembered is not None:
        category = db.get(Category, remembered.category_id)
        if category is not None:
            return category, "memory"
    name = match_rule(description, amount_cents)
    if name is None:
        return None
    for category in db.scalars(select(Category).where(Category.name == name)):
        if category.applies_to(CategoryScope.personal):
            return category, "rule"
    return None
