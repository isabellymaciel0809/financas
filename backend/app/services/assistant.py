"""Assistente financeiro: a LLM responde perguntas consultando o banco por meio de ferramentas.

Princípio de projeto: a LLM só escolhe a intenção; o backend faz todo o resto.
Testes com um modelo local de 3B mostraram que ele erra contas de datas, esquece de separar
receitas de despesas e copia sinais negativos para a resposta. Por isso:
- períodos são opções fechadas ("mes_passado") e o backend calcula as datas; quando a pergunta
  diz o período ("nos últimos 3 meses", "em setembro"), o backend o tira do próprio texto;
- a ferramenta `gastos` só enxerga despesas e devolve valores positivos;
- todo valor volta já formatado em reais, então não sobra conta para a LLM fazer.

Os argumentos são validados com Pydantic; um argumento inválido volta para a LLM como erro,
para ela corrigir e tentar de novo.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Transaction
from app.services.categorizer.llm import ChatResult, LLMProvider, ToolSpec
from app.services.text import simplify

UNCATEGORIZED = "Sem categoria"

Period = Literal[
    "este_mes",
    "mes_passado",
    "ultimos_3_meses",
    "ultimos_6_meses",
    "este_ano",
    "ano_passado",
    "tudo",
]

PERIOD_HELP = (
    "este_mes = do dia 1 do mês atual até hoje; mes_passado = o mês anterior inteiro; "
    "ultimos_3_meses e ultimos_6_meses incluem o mês atual; este_ano = desde 1º de janeiro; "
    "tudo = todo o histórico."
)


def brl(cents: int) -> str:
    value = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}R$ {value}"


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def resolve_period(period: Period, month: str | None, today: date) -> tuple[date, date]:
    """Devolve (início, fim) inclusivos. `month` (AAAA-MM) tem prioridade sobre `period`."""
    if month:
        start = date(int(month[:4]), int(month[5:7]), 1)
        return start, _add_months(start, 1) - timedelta(days=1)
    first_of_month = today.replace(day=1)
    match period:
        case "este_mes":
            return first_of_month, today
        case "mes_passado":
            return _add_months(first_of_month, -1), first_of_month - timedelta(days=1)
        case "ultimos_3_meses":
            return _add_months(first_of_month, -2), today
        case "ultimos_6_meses":
            return _add_months(first_of_month, -5), today
        case "este_ano":
            return date(today.year, 1, 1), today
        case "ano_passado":
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        case _:
            return date(1900, 1, 1), today


MONTH_NAMES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip
_PLAIN_MONTHS = [simplify(m) for m in MONTH_NAMES]

# Como o período aparece para a LLM. Só com as datas ("01/09 a 11/11"), o qwen2.5:3b escrevia
# "no último mês" em perguntas de 3 meses; com o nome, ele tem a frase certa para copiar.
PERIOD_NAMES: dict[str, str] = {
    "este_mes": "este mês",
    "mes_passado": "mês passado",
    "ultimos_3_meses": "últimos 3 meses",
    "ultimos_6_meses": "últimos 6 meses",
    "este_ano": "este ano",
    "ano_passado": "ano passado",
    "tudo": "todo o histórico",
}

_TEXT_PERIODS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:[nd]?este|[nd]?esse) mes\b|\bmes atual\b"), "este_mes"),
    (re.compile(r"\bmes passado\b|\bultimo mes\b"), "mes_passado"),
    (re.compile(r"\bultimos (?:3|tres) meses\b"), "ultimos_3_meses"),
    (re.compile(r"\bultimos (?:6|seis) meses\b"), "ultimos_6_meses"),
    (re.compile(r"\b(?:[nd]?este|[nd]?esse) ano\b"), "este_ano"),
    (re.compile(r"\bano passado\b"), "ano_passado"),
]
_MONTH_NAME = re.compile(r"\b(" + "|".join(_PLAIN_MONTHS) + r")\b(?: de (\d{4}))?")
_PER_MONTH = re.compile(r"\bpor mes\b|\bmes a mes\b|\bcada mes\b|\bmensalmente\b")
# Comparações. O qwen2.5:3b respondia "gastei mais que no mês passado?" consultando um mês só:
# comparar exige duas consultas e uma conta, e ele não faz nenhuma das duas.
_COMPARE = re.compile(
    r"\bcompar|\bem relacao (?:a|ao)\b|\bdiferenca\b|\baument|\bdiminu"
    # "mais que no mês passado", "menos com Uber do que em setembro": depois do "que" vem um
    # período. Sem isso, "a coisa mais cara que comprei esse mês" (o "que" abre outra frase)
    # virava comparação.
    r"|\b(?:mais|menos)(?: \w+){0,3} (?:do )?que (?:(?:no|na|em|o|a) )?"
    r"(?:mes|ano|ultimos?|" + "|".join(_PLAIN_MONTHS) + r")\b"
)
# "Em qual mês", "em que mês", mas não "a mais que mês passado".
_WHICH_MONTH = re.compile(r"\bqual mes\b|\bquais meses\b|(?:^|\bem |\bde )que mes\b")
_MORE_OR_LESS = re.compile(r"\b(?:mais|menos|maior|menor)\b")


def periods_in_text(text: str, today: date) -> list[dict[str, str]]:
    """Todos os períodos ditos na pergunta, sem repetir: [{"periodo": ...}, {"mes": "AAAA-MM"}]."""
    plain = simplify(text)
    found: list[dict[str, str]] = [
        {"periodo": period} for pattern, period in _TEXT_PERIODS if pattern.search(plain)
    ]
    for match in _MONTH_NAME.finditer(plain):
        month = _PLAIN_MONTHS.index(match.group(1)) + 1
        if match.group(2):
            year = int(match.group(2))
        else:  # "em setembro" dito em março: setembro passado
            year = today.year if month <= today.month else today.year - 1
        if (item := {"mes": f"{year}-{month:02d}"}) not in found:
            found.append(item)
    return found


def period_from_text(text: str, today: date) -> dict[str, str] | None:
    """Período dito com todas as letras na pergunta: {"periodo": ...} ou {"mes": "AAAA-MM"}.

    Na avaliação, o qwen2.5:3b mandava `mes` em quase toda chamada, mesmo quando a pergunta era
    "nos últimos 3 meses", e o mês tem prioridade: a resposta saía de um mês só. Quando o texto
    é claro, o backend decide; se não houver período, ou houver mais de um, quem decide é a LLM.
    """
    found = periods_in_text(text, today)
    return found[0] if len(found) == 1 else None


def _month_name(day: date) -> str:
    return f"{MONTH_NAMES[day.month - 1]} de {day.year}"


def _label(name: str, start: date, end: date) -> str:
    return f"{name} ({start:%d/%m/%Y} a {end:%d/%m/%Y})"


def _as_base(period: dict[str, str]) -> dict[str, str]:
    """{"periodo": X} vira {"comparar_com": X}; {"mes": X} vira {"comparar_com_mes": X}."""
    ((key, value),) = period.items()
    return {"comparar_com" if key == "periodo" else "comparar_com_mes": value}


def _difference(cents: int) -> str:
    if cents == 0:
        return "igual: nenhuma diferença"
    return f"{brl(abs(cents))} a {'mais' if cents > 0 else 'menos'}"


class PeriodArgs(BaseModel):
    periodo: Period = "este_mes"
    mes: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")


class SpendingArgs(PeriodArgs):
    categoria: str | None = None
    estabelecimento: str | None = Field(None, max_length=60)
    limite: int = Field(5, ge=1, le=20)

    @field_validator("limite", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> Any:
        return int(value) if isinstance(value, str) and value.isdigit() else value


class CompareArgs(SpendingArgs):
    """Argumentos de `comparar_gastos`, que a LLM não vê: o backend preenche pela pergunta."""

    # Sem nenhum dos dois: o período do mesmo tamanho logo antes (este mês -> mês passado).
    comparar_com: Period | None = None
    comparar_com_mes: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")


class MonthlyArgs(BaseModel):
    meses: int = Field(6, ge=1, le=24)
    # Não aparece para a LLM: o backend liga quando a pergunta é sobre gastos por mês.
    so_despesas: bool = False


_PERIOD_PROPERTIES = {
    "periodo": {
        "type": "string",
        "enum": list(Period.__args__),
        "description": PERIOD_HELP,
    },
    "mes": {
        "type": "string",
        "description": "Mês específico no formato AAAA-MM (ex.: 2026-10). Substitui 'periodo'.",
    },
}

_FILTER_PROPERTIES = {
    "categoria": {"type": "string", "description": "Nome exato de uma categoria"},
    "estabelecimento": {
        "type": "string",
        "description": "Trecho do nome na descrição, ex.: 'uber'",
    },
}

TOOLS = [
    ToolSpec(
        name="gastos",
        description=(
            "Quanto foi GASTO (só despesas) em um período: total, divisão por categoria e as "
            "maiores despesas. Use para 'quanto gastei', 'maiores gastos', 'gastos com X'. "
            "Para um estabelecimento ou app (Uber, iFood, Netflix), use 'estabelecimento'; "
            "para um tipo de gasto (Alimentação, Transporte), use 'categoria'."
        ),
        parameters={
            "type": "object",
            "properties": {
                **_PERIOD_PROPERTIES,
                **_FILTER_PROPERTIES,
                "limite": {
                    "type": "integer",
                    "description": "Quantas das maiores despesas listar (padrão 5)",
                },
            },
        },
    ),
    # `comparar_gastos` não está aqui de propósito: com ela como quarta ferramenta, o qwen2.5:3b
    # passou a errar perguntas que acertava ("quanto gastei este mês?" virou resumo_financeiro).
    # O backend a usa quando a pergunta compara com todas as letras (ver `Toolbox.route`).
    ToolSpec(
        name="resumo_financeiro",
        description=(
            "Receitas, despesas e saldo de um período, com as receitas por categoria. Use para "
            "'quanto recebi', 'qual meu saldo', 'sobrou dinheiro?'."
        ),
        parameters={"type": "object", "properties": _PERIOD_PROPERTIES},
    ),
    ToolSpec(
        name="evolucao_mensal",
        description=(
            "Receitas, despesas e saldo mês a mês, para ver tendência. Diz também o mês com mais "
            "e com menos despesas: use para 'em qual mês gastei mais?'."
        ),
        parameters={
            "type": "object",
            "properties": {"meses": {"type": "integer", "description": "Quantos meses (1 a 24)"}},
        },
    ),
]

SYSTEM_TEMPLATE = """Você é o assistente de um app de finanças pessoais. Responda em português \
do Brasil, em no máximo três frases curtas ou uma lista curta.

Hoje é {today}. Categorias: {categories}.

Sempre use uma ferramenta antes de responder sobre valores, e copie os valores exatamente como \
a ferramenta devolveu: nunca calcule, estime ou invente números. Se a ferramenta não encontrar \
nada, diga isso. Ao citar o período, use o nome que vem no campo "periodo" do resultado \
(ex.: "nos últimos 3 meses"). Se a pergunta não for sobre as finanças do usuário, diga que \
você só responde sobre os dados do app."""


class Toolbox:
    """Executa as ferramentas do assistente sobre o banco."""

    def __init__(self, db: Session, today: date | None = None, question: str | None = None):
        self.db = db
        self.today = today or date.today()
        self.categories = list(db.scalars(select(Category).order_by(Category.name)))
        plain = simplify(question or "")
        self.periods_said = periods_in_text(plain, self.today) if question else []
        self.period_hint = self.periods_said[0] if len(self.periods_said) == 1 else None
        self.per_month = bool(_PER_MONTH.search(plain))
        more_or_less = bool(_MORE_OR_LESS.search(plain))
        # "Gastei mais em outubro ou em setembro?" compara sem dizer "comparar".
        self.compare = bool(_COMPARE.search(plain)) or (
            more_or_less and len(self.periods_said) >= 2
        )
        self.which_month = more_or_less and bool(_WHICH_MONTH.search(plain))

    def _fix_period(self, arguments: dict[str, Any]) -> dict[str, Any]:
        fixed = dict(arguments)
        if self.period_hint:
            fixed.pop("periodo", None)
            fixed.pop("mes", None)
            fixed.update(self.period_hint)
        # E às vezes põem um período no campo do mês ({"mes": "este_mes"}). Com o qwen2.5:3b, isso
        # virava erro e o modelo desistia em vez de corrigir: o backend entende sozinho.
        if fixed.get("mes") in Period.__args__:
            fixed.setdefault("periodo", fixed.pop("mes"))
        return fixed

    def route(self, name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """A ferramenta e os argumentos que o backend vai de fato executar."""
        # Modelos pequenos às vezes mandam campos vazios ou "null" em vez de omitir.
        cleaned = {k: v for k, v in arguments.items() if v not in (None, "", "null", "None")}
        spending = name in ("gastos", "comparar_gastos")
        filtered = bool(cleaned.get("categoria") or cleaned.get("estabelecimento"))
        # "Em qual mês gastei mais?": a evolução mensal já diz o mês com mais e com menos
        # despesas. Com filtro ela não serve (não filtra), então segue a comparação ou `gastos`.
        if spending and self.which_month and not filtered:
            months = self._months_until_today(cleaned) or 6
            return "evolucao_mensal", {"meses": months, "so_despesas": True}
        if name == "comparar_gastos" or (name == "gastos" and self.compare):
            return "comparar_gastos", self._comparison(name, cleaned)
        if name in ("gastos", "resumo_financeiro"):
            cleaned = self._fix_period(cleaned)
        # "Quanto gastei por mês nos últimos 3 meses?": na avaliação, o qwen2.5:3b chamou `gastos`,
        # que soma o período inteiro, e citou valores que não respondiam à pergunta. Sem filtro e
        # com um período que termina hoje, a evolução mensal responde exatamente isso.
        if name == "gastos" and self.per_month:
            months = self._months_until_today(cleaned)
            if months and not (cleaned.get("categoria") or cleaned.get("estabelecimento")):
                return "evolucao_mensal", {"meses": months, "so_despesas": True}
        return name, cleaned

    def _comparison(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Os dois períodos da comparação, tirados da pergunta quando ela os diz.

        - Um período ("a mais que no mês passado", "comparado com setembro"): é o "antes", e o
          "agora" é este mês. Se o período dito é este mês, o "antes" é o mês passado.
        - Dois ("outubro e setembro"): o mais recente é o "agora", em qualquer ordem na frase.
        - Nenhum: vale o que o modelo mandou, se ele chamou `comparar_gastos`; senão, este mês
          contra o mês passado.
        """
        keep = ("categoria", "estabelecimento", "limite")
        filters = {k: v for k, v in arguments.items() if k in keep}

        def start(period: dict[str, str]) -> date:
            return resolve_period(period.get("periodo", "tudo"), period.get("mes"), self.today)[0]

        said = self.periods_said
        if not said:
            return arguments if name == "comparar_gastos" else filters
        if len(said) == 1:
            # "Este mês" ou "novembro" dito em novembro: é o "agora"; o "antes" é o mês passado.
            if start(said[0]) == self.today.replace(day=1):
                return filters
            return {**filters, **_as_base(said[0])}
        first, second = said[:2]
        now, before = (first, second) if start(first) >= start(second) else (second, first)
        return {**filters, **now, **_as_base(before)}

    def _months_until_today(self, arguments: dict[str, Any]) -> int | None:
        try:
            args = PeriodArgs.model_validate(
                {k: v for k, v in arguments.items() if k in ("periodo", "mes")}
            )
        except ValidationError:
            return None
        start, end = resolve_period(args.periodo, args.mes, self.today)
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        return months if end == self.today and 2 <= months <= 24 else None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "gastos": (SpendingArgs, self.gastos),
            "comparar_gastos": (CompareArgs, self.comparar_gastos),
            "resumo_financeiro": (PeriodArgs, self.resumo_financeiro),
            "evolucao_mensal": (MonthlyArgs, self.evolucao_mensal),
        }
        if name not in handlers:
            return {"erro": f"Ferramenta desconhecida: {name}. Use: {', '.join(handlers)}"}
        name, cleaned = self.route(name, arguments)
        schema, handler = handlers[name]
        try:
            args = schema.model_validate(cleaned)
        except ValidationError as exc:
            return {"erro": f"Argumentos inválidos: {exc.errors(include_url=False)}"}
        try:
            return handler(args)
        except ValueError as exc:
            return {"erro": str(exc)}

    def _period(self, args: PeriodArgs) -> tuple[date, date, str]:
        start, end = resolve_period(args.periodo, args.mes, self.today)
        name = _month_name(start) if args.mes else PERIOD_NAMES[args.periodo]
        return start, end, _label(name, start, end)

    def _base_period(self, args: CompareArgs, start: date, end: date) -> tuple[date, date, str]:
        """O período de comparação: o pedido ou, sem pedido, o do mesmo tamanho logo antes."""
        if args.comparar_com or args.comparar_com_mes:
            return self._period(
                PeriodArgs(periodo=args.comparar_com or "tudo", mes=args.comparar_com_mes)
            )
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        base_start = _add_months(start.replace(day=1), -months)
        base_end = start.replace(day=1) - timedelta(days=1)
        name = _month_name(base_start) if months == 1 else f"os {months} meses anteriores"
        return base_start, base_end, _label(name, base_start, base_end)

    def _resolve_category(self, name: str) -> Category:
        wanted = simplify(name)
        for category in self.categories:
            if simplify(category.name) == wanted:
                return category
        valid = ", ".join(c.name for c in self.categories)
        raise ValueError(f"Categoria '{name}' não existe. Use uma destas: {valid}")

    def _in_period(self, start: date, end: date):
        return (Transaction.date >= start, Transaction.date < end + timedelta(days=1))

    def _is_merchant(self, name: str) -> bool:
        """Algum gasto, em qualquer data, tem esse nome na descrição?"""
        expense = (Transaction.amount_cents < 0, Transaction.description.ilike(f"%{name}%"))
        return self.db.scalar(select(Transaction.id).where(*expense).limit(1)) is not None

    def _spending_filter(self, args: SpendingArgs) -> tuple[list[Any], str, str | None]:
        """Condições de categoria e estabelecimento, o nome do filtro e uma observação."""
        conditions: list[Any] = [Transaction.amount_cents < 0]
        category, merchant, note = None, args.estabelecimento, None
        if args.categoria:
            try:
                category = self._resolve_category(args.categoria)
            except ValueError:
                # Na avaliação, o modelo pôs "Netflix" como categoria, recebeu o erro e respondeu
                # "não foram encontrados gastos": uma resposta errada que parece certa. Se o nome
                # aparece nas descrições, a busca vira por estabelecimento; senão, o erro volta.
                if merchant or not self._is_merchant(args.categoria):
                    raise
                merchant = args.categoria
                note = f"'{merchant}' não é uma categoria: a busca foi pelo nome na descrição."
        if category:
            conditions.append(Transaction.category_id == category.id)
        if merchant:
            conditions.append(Transaction.description.ilike(f"%{merchant}%"))
        names = [f for f in (category.name if category else None, merchant) if f]
        return conditions, " / ".join(names) or "todas as despesas", note

    def _spent(self, conditions: list[Any], start: date, end: date) -> list[Transaction]:
        query = select(Transaction).where(*conditions, *self._in_period(start, end))
        return list(self.db.scalars(query))

    @staticmethod
    def _by_category(transactions: list[Transaction]) -> dict[str, int]:
        totals: dict[str, int] = {}
        for tx in transactions:
            name = tx.category.name if tx.category else UNCATEGORIZED
            totals[name] = totals.get(name, 0) - tx.amount_cents
        return totals

    def gastos(self, args: SpendingArgs) -> dict[str, Any]:
        start, end, label = self._period(args)
        conditions, filter_name, note = self._spending_filter(args)
        transactions = self._spent(conditions, start, end)
        total = -sum(tx.amount_cents for tx in transactions)
        by_category = self._by_category(transactions)
        largest = sorted(transactions, key=lambda tx: tx.amount_cents)[: args.limite]

        return {
            "periodo": label,
            "filtro": filter_name,
            **({"observacao": note} if note else {}),
            "total_gasto": brl(total),
            "quantidade_de_despesas": len(transactions),
            "por_categoria": [
                {"categoria": k, "total": brl(v)}
                for k, v in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
            ],
            "maiores_despesas": [
                {
                    "data": f"{tx.date:%d/%m/%Y}",
                    "descricao": tx.description,
                    "valor": brl(-tx.amount_cents),
                    "categoria": tx.category.name if tx.category else UNCATEGORIZED,
                }
                for tx in largest
            ],
        }

    def comparar_gastos(self, args: CompareArgs) -> dict[str, Any]:
        start, end, label = self._period(args)
        base_start, base_end, base_label = self._base_period(args, start, end)
        conditions, filter_name, note = self._spending_filter(args)
        now = self._by_category(self._spent(conditions, start, end))
        before = self._by_category(self._spent(conditions, base_start, base_end))
        total, base_total = sum(now.values()), sum(before.values())

        changes = [(name, before.get(name, 0), now.get(name, 0)) for name in {*now, *before}]
        changes.sort(key=lambda c: c[2] - c[1], reverse=True)
        increased = [c for c in changes if c[2] > c[1]][: args.limite]
        decreased = [c for c in reversed(changes) if c[2] < c[1]][: args.limite]

        notes = [note] if note else []
        last_day = _add_months(end.replace(day=1), 1) - timedelta(days=1)
        if end == self.today and self.today != last_day and base_end < start:
            # Novembro até o dia 11 contra outubro inteiro: menos gasto pode ser só menos dias.
            notes.append(
                f"O período ainda não terminou (vai até hoje, {self.today:%d/%m/%Y}); "
                "o período comparado está completo."
            )
        return {
            "periodo": label,
            "comparado_com": base_label,
            "filtro": filter_name,
            **({"observacao": " ".join(notes)} if notes else {}),
            "gasto_no_periodo": brl(total),
            "gasto_no_comparado": brl(base_total),
            "diferenca": _difference(total - base_total),
            "categorias_que_aumentaram": [
                {"categoria": n, "antes": brl(b), "agora": brl(a), "aumento": brl(a - b)}
                for n, b, a in increased
            ],
            "categorias_que_diminuiram": [
                {"categoria": n, "antes": brl(b), "agora": brl(a), "reducao": brl(b - a)}
                for n, b, a in decreased
            ],
        }

    def resumo_financeiro(self, args: PeriodArgs) -> dict[str, Any]:
        start, end, label = self._period(args)
        rows = self.db.execute(
            select(Transaction.amount_cents, Category.name)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(*self._in_period(start, end))
        ).all()
        income = sum(a for a, _ in rows if a > 0)
        expense = -sum(a for a, _ in rows if a < 0)
        by_income: dict[str, int] = {}
        for amount, category in rows:
            if amount > 0:
                key = category or UNCATEGORIZED
                by_income[key] = by_income.get(key, 0) + amount
        return {
            "periodo": label,
            "receitas": brl(income),
            "despesas": brl(expense),
            "saldo": brl(income - expense),
            "situacao": "sobrou dinheiro" if income >= expense else "gastou mais do que recebeu",
            "receitas_por_categoria": [
                {"categoria": k, "total": brl(v)}
                for k, v in sorted(by_income.items(), key=lambda kv: kv[1], reverse=True)
            ],
        }

    def evolucao_mensal(self, args: MonthlyArgs) -> dict[str, Any]:
        first = _add_months(self.today.replace(day=1), -(args.meses - 1))
        rows = self.db.execute(
            select(Transaction.date, Transaction.amount_cents).where(
                *self._in_period(first, self.today)
            )
        ).all()
        totals = {_add_months(first, i): [0, 0] for i in range(args.meses)}
        for tx_date, amount in rows:
            totals[tx_date.replace(day=1)][0 if amount > 0 else 1] += abs(amount)
        extremes = self._extremes({m: exp for m, (_, exp) in totals.items()})
        if args.so_despesas:
            # Com receitas e saldo no resultado, o qwen2.5:3b citou o saldo de cada mês como se
            # fosse o gasto: valores reais, que a checagem de fatos não pega, no campo errado.
            return {
                "meses": [
                    {"mes": f"{m:%m/%Y}", "despesas": brl(exp)} for m, (_, exp) in totals.items()
                ],
                **extremes,
            }
        return {
            "meses": [
                {
                    "mes": f"{m:%m/%Y}",
                    "receitas": brl(inc),
                    "despesas": brl(exp),
                    "saldo": brl(inc - exp),
                }
                for m, (inc, exp) in totals.items()
            ],
            **extremes,
        }

    def _extremes(self, spent: dict[date, int]) -> dict[str, Any]:
        """O mês com mais e com menos despesas, para a LLM não ter de comparar os números.

        Meses sem nenhuma despesa (antes de começar a usar o app) não contam como "o que gastou
        menos". O mês atual conta, com um aviso de que ainda não terminou.
        """
        months = {m: v for m, v in spent.items() if v > 0}
        if len(months) < 2:
            return {}
        most, least = max(months, key=months.get), min(months, key=months.get)
        result: dict[str, Any] = {
            "mes_com_mais_despesas": {"mes": f"{most:%m/%Y}", "despesas": brl(months[most])},
            "mes_com_menos_despesas": {"mes": f"{least:%m/%Y}", "despesas": brl(months[least])},
        }
        current = self.today.replace(day=1)
        if current in months:
            result["observacao"] = (
                f"{current:%m/%Y} ainda não terminou: vai até hoje ({self.today:%d/%m/%Y})."
            )
        return result


# Aceita "R$ 1.234,56" e também "R$ 1234,56" (o modelo nem sempre usa separador de milhar).
_MONEY = re.compile(r"R\$\s*-?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")


def money_values(text: str) -> dict[int, str]:
    """Valores em reais citados num texto, em centavos (sem sinal) -> como apareceram."""
    found: dict[int, str] = {}
    for match in _MONEY.finditer(text):
        raw = match.group(1).replace(".", "")
        reais, _, centavos = raw.partition(",")
        found[int(reais) * 100 + int(centavos.ljust(2, "0") or 0)] = match.group(0)
    return found


@dataclass
class Answer:
    result: ChatResult
    # Valores da resposta que não aparecem em nenhum resultado de ferramenta.
    unverified_values: list[str]


def ask(
    db: Session,
    provider: LLMProvider,
    messages: list[dict[str, str]],
    today: date | None = None,
) -> Answer:
    question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), None)
    toolbox = Toolbox(db, today, question)
    system = SYSTEM_TEMPLATE.format(
        today=f"{toolbox.today:%d/%m/%Y}",
        categories=", ".join(c.name for c in toolbox.categories),
    )
    tool_outputs: list[str] = []

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        output = toolbox.execute(name, arguments)
        tool_outputs.append(json.dumps(output, ensure_ascii=False))
        return output

    result = provider.chat_with_tools(system, messages, TOOLS, execute)

    # Checagem de fatos: todo valor citado precisa ter vindo de uma ferramenta.
    grounded = money_values(" ".join(tool_outputs))
    unverified = [
        raw for cents, raw in money_values(result.answer).items() if cents not in grounded
    ]
    return Answer(result=result, unverified_values=unverified)
